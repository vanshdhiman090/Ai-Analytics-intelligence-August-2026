"""Deterministic V0 root-cause investigation engine.

The engine evaluates typed inputs only.  It does not execute model-authored
code, invent hypotheses, or upgrade observational evidence into causality.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

import pandas as pd

from app.services.tabular import DateSemanticError, parse_date_series
from app.services.comparison_context import extract_explicit_comparison_context
from app.services.hypothesis_planner import plan_hypotheses, update_hypothesis_statuses
from app.services.investigation_controller import choose_next_action

from app.domain.root_cause_contracts import (
    AdditiveKPISemanticDefinition,
    DataHealthCheck,
    DataHealthAssessment,
    DriverInput,
    DriverContribution,
    EvidenceStrength,
    HypothesisAssessment,
    HypothesisInput,
    IncidentInput,
    IncidentAssessment,
    RCAConclusion,
    RCAEvidence,
    RCAInvestigationReport,
    RCAInvestigationRequest,
    RCASemanticDefinition,
    ReconciliationAssessment,
    DimensionContributionTest,
    InvestigationEvidence,
    InvestigationHealthCheck,
    InvestigationHypothesis,
    HypothesisPlanningRecord,
    InvestigationFilter,
    InvestigationIteration,
    InvestigationPathNode,
    InvestigationState,
    SegmentContribution,
    SingleLevelInvestigationRequest,
)


_QUALITY_SCORE = {"insufficient": 0, "caution": 1, "ready": 2}
_CAUSAL_TYPES = {"experimental", "quasi_experimental"}
def _strength(evidence_ids: Iterable[str], evidence: dict[str, RCAEvidence]) -> EvidenceStrength:
    items = [evidence[item_id] for item_id in dict.fromkeys(evidence_ids)]
    if not items or any(_QUALITY_SCORE[item.quality] == 0 for item in items):
        return "low"
    distinct_sources = {item.source_id for item in items}
    if all(item.quality == "ready" for item in items) and (
        len(distinct_sources) >= 2 or any(item.evidence_type in _CAUSAL_TYPES for item in items)
    ):
        return "high"
    return "medium"


def _incident(request: RCAInvestigationRequest) -> IncidentAssessment:
    source = request.incident
    change = source.comparison_value - source.baseline_value
    percent_change = change / abs(source.baseline_value) * 100 if source.baseline_value != 0 else None
    direction = "increase" if change > 0 else "decrease" if change < 0 else "no_change"
    return IncidentAssessment(
        metric=source.metric,
        unit=source.unit,
        baseline_period=source.baseline_period,
        comparison_period=source.comparison_period,
        baseline_value=source.baseline_value,
        comparison_value=source.comparison_value,
        absolute_change=change,
        percent_change=percent_change,
        direction=direction,
        evidence_ids=source.evidence_ids,
    )


def _data_health(
    request: RCAInvestigationRequest, evidence: dict[str, RCAEvidence]
) -> DataHealthAssessment:
    checks = request.data_health_checks
    blocking = tuple(item.detail for item in checks if item.status == "fail" and item.blocking)
    cautions = tuple(
        item.detail for item in checks if item.status in {"caution", "unknown"} or (item.status == "fail" and not item.blocking)
    )
    if blocking:
        status = "fail"
    elif not checks:
        status = "unknown"
        cautions = ("No explicit data-health checks were supplied.",)
    elif any(item.status in {"caution", "fail", "unknown"} for item in checks):
        status = "caution"
    else:
        status = "pass"
    cited = [evidence_id for item in checks for evidence_id in item.evidence_ids]
    return DataHealthAssessment(
        status=status,
        blocking_failures=blocking,
        cautions=cautions,
        evidence_strength=_strength(cited, evidence),
    )


def _drivers(
    request: RCAInvestigationRequest,
    incident: IncidentAssessment,
    evidence: dict[str, RCAEvidence],
) -> tuple[DriverContribution, ...]:
    results: list[DriverContribution] = []
    for item in request.drivers:
        change = item.comparison_value - item.baseline_value
        share = change / incident.absolute_change * 100 if incident.absolute_change != 0 else None
        direction = (
            "neutral" if change == 0 or incident.absolute_change == 0
            else "with_incident" if change * incident.absolute_change > 0
            else "against_incident"
        )
        results.append(
            DriverContribution(
                driver_id=item.driver_id,
                name=item.name,
                baseline_value=item.baseline_value,
                comparison_value=item.comparison_value,
                absolute_change=change,
                contribution_to_total_change_pct=share,
                direction=direction,
                evidence_ids=item.evidence_ids,
                evidence_strength=_strength(item.evidence_ids, evidence),
            )
        )
    return tuple(sorted(results, key=lambda item: (-abs(item.absolute_change), item.driver_id)))


def _reconciliation(
    request: RCAInvestigationRequest,
    incident: IncidentAssessment,
    drivers: tuple[DriverContribution, ...],
) -> ReconciliationAssessment:
    if not request.drivers_form_partition:
        return ReconciliationAssessment(
            reconcilable=False,
            incident_change=incident.absolute_change,
            explained_change=None,
            unexplained_change=None,
            explained_pct=None,
            unexplained_pct=None,
            residual_within_tolerance=None,
            note="Drivers are not declared mutually exclusive and exhaustive; their changes cannot be added safely.",
        )
    explained = sum(item.absolute_change for item in drivers)
    residual = incident.absolute_change - explained
    if incident.absolute_change == 0:
        explained_pct = unexplained_pct = None
        within_tolerance = abs(residual) <= 1e-9
    else:
        explained_pct = explained / incident.absolute_change * 100
        unexplained_pct = residual / incident.absolute_change * 100
        tolerance = abs(incident.absolute_change) * request.reconciliation_tolerance_pct / 100
        within_tolerance = abs(residual) <= max(tolerance, 1e-9)
    return ReconciliationAssessment(
        reconcilable=True,
        incident_change=incident.absolute_change,
        explained_change=explained,
        unexplained_change=residual,
        explained_pct=explained_pct,
        unexplained_pct=unexplained_pct,
        residual_within_tolerance=within_tolerance,
        note=(
            "Driver changes reconcile to the observed incident movement."
            if within_tolerance
            else "Driver changes do not fully reconcile; the residual remains explicitly unexplained."
        ),
    )


def _assess_hypothesis(
    hypothesis: HypothesisInput, evidence: dict[str, RCAEvidence]
) -> HypothesisAssessment:
    falsified = any(item.outcome == "falsified" for item in hypothesis.falsification_checks)
    survived = any(item.outcome == "survived" for item in hypothesis.falsification_checks)
    untested = not hypothesis.falsification_checks or any(
        item.outcome in {"not_run", "inconclusive"} for item in hypothesis.falsification_checks
    )
    support = hypothesis.supporting_evidence_ids
    contradiction = hypothesis.contradicting_evidence_ids
    mechanism = hypothesis.mechanism_evidence_ids
    all_ids = tuple(dict.fromkeys((*support, *contradiction, *mechanism)))
    strength = _strength(all_ids, evidence)
    causal_evidence = any(evidence[item_id].evidence_type in _CAUSAL_TYPES for item_id in mechanism)

    if falsified or contradiction:
        status = "rejected"
        rationale = "Contradicting evidence or a falsification test rejects this hypothesis."
    elif support and mechanism and survived and not untested and strength in {"medium", "high"}:
        status = "supported"
        rationale = "Supporting and mechanism evidence survived all recorded falsification checks."
    elif support and (mechanism or survived):
        status = "partially_supported"
        rationale = "Some predicted evidence is present, but mechanism or falsification coverage is incomplete."
    else:
        status = "unresolved"
        rationale = "The available evidence is insufficient to support or reject this hypothesis."

    return HypothesisAssessment(
        hypothesis_id=hypothesis.hypothesis_id,
        statement=hypothesis.statement,
        status=status,
        evidence_strength=strength,
        supporting_evidence_ids=support,
        contradicting_evidence_ids=contradiction,
        mechanism_evidence_ids=mechanism,
        falsification_outcomes=tuple(
            f"{item.check_id}:{item.outcome}" for item in hypothesis.falsification_checks
        ),
        causal_evidence_present=causal_evidence,
        rationale=rationale,
    )


def _conclusion(
    incident: IncidentAssessment,
    health: DataHealthAssessment,
    drivers: tuple[DriverContribution, ...],
    reconciliation: ReconciliationAssessment,
    hypotheses: tuple[HypothesisAssessment, ...],
) -> RCAConclusion:
    primary = next((item for item in drivers if item.direction == "with_incident"), None)
    supported = next(
        (
            item for item in hypotheses
            if item.status == "supported" and item.causal_evidence_present and item.evidence_strength == "high"
        ),
        None,
    )
    incident_strength = min(
        (item.evidence_strength for item in drivers),
        key={"low": 0, "medium": 1, "high": 2}.get,
        default="low",
    )

    if incident.absolute_change == 0:
        reason = "The comparison contains no KPI movement to explain."
    elif health.status == "fail":
        reason = "A blocking data-health failure makes the incident evidence unsafe to interpret."
    elif primary is None:
        reason = "No measured driver moves in the same direction as the incident."
    elif not reconciliation.reconcilable:
        reason = "The supplied drivers are overlapping or incomplete, so explained movement cannot be reconciled."
    elif reconciliation.residual_within_tolerance is not True:
        reason = "The supplied driver decomposition leaves material unexplained movement."
    elif primary.evidence_strength == "low":
        reason = "The leading mathematical driver has insufficient evidence quality."
    else:
        reason = None

    if reason:
        return RCAConclusion(
            determination="inconclusive",
            statement="I cannot determine the root cause from the available evidence.",
            primary_driver_id=primary.driver_id if primary else None,
            evidence_strength=incident_strength,
            abstention_reason=reason,
        )

    if supported is not None and health.status == "pass":
        return RCAConclusion(
            determination="causal_root_cause_supported",
            statement=(
                f"{supported.statement} is supported as the root cause of the observed {incident.metric} movement; "
                "the conclusion is limited to the cited evidence and comparison window."
            ),
            primary_driver_id=primary.driver_id,
            leading_hypothesis_id=supported.hypothesis_id,
            causal_claim_allowed=True,
            evidence_strength="high",
        )

    return RCAConclusion(
        determination="mathematical_driver_identified",
        statement=(
            f"{primary.name} is the largest measured mathematical contributor to the observed "
            f"{incident.metric} movement; a causal root cause is not established."
        ),
        primary_driver_id=primary.driver_id,
        leading_hypothesis_id=next(
            (item.hypothesis_id for item in hypotheses if item.status in {"supported", "partially_supported"}),
            None,
        ),
        causal_claim_allowed=False,
        evidence_strength=primary.evidence_strength,
        abstention_reason="No high-strength causal hypothesis passed the required evidence and falsification gates.",
    )


def investigate_root_cause(request: RCAInvestigationRequest) -> RCAInvestigationReport:
    """Run a deterministic investigation and return a fully typed report."""

    evidence = {item.evidence_id: item for item in request.evidence}
    incident = _incident(request)
    health = _data_health(request, evidence)
    drivers = _drivers(request, incident, evidence)
    reconciliation = _reconciliation(request, incident, drivers)
    hypotheses = tuple(_assess_hypothesis(item, evidence) for item in request.hypotheses)
    conclusion = _conclusion(incident, health, drivers, reconciliation, hypotheses)

    next_steps: list[str] = []
    if health.status in {"fail", "unknown", "caution"}:
        next_steps.append("Resolve or explicitly accept the recorded data-health limitations before escalation.")
    if reconciliation.reconcilable and reconciliation.residual_within_tolerance is False:
        next_steps.append("Measure additional mutually exclusive drivers for the unexplained movement.")
    if not reconciliation.reconcilable:
        next_steps.append("Provide a mutually exclusive, exhaustive driver decomposition.")
    if not hypotheses:
        next_steps.append("Define competing mechanism hypotheses and pre-specified falsification checks.")
    elif not any(item.status == "supported" and item.causal_evidence_present for item in hypotheses):
        next_steps.append("Collect mechanism-level or causal evidence for the leading hypothesis.")
    if not next_steps:
        next_steps.append("Monitor the KPI and repeat the same checks on the next complete comparison window.")

    limitations = [
        "Mathematical contribution does not by itself establish causality.",
        "The conclusion applies only to the supplied evidence and comparison periods.",
    ]
    if incident.percent_change is None:
        limitations.append("Percentage change is undefined because the baseline value is zero.")
    limitations.extend(health.cautions)

    return RCAInvestigationReport(
        incident=incident,
        data_health=health,
        drivers=drivers,
        reconciliation=reconciliation,
        hypotheses=hypotheses,
        conclusion=conclusion,
        next_investigations=tuple(dict.fromkeys(next_steps)),
        limitations=tuple(dict.fromkeys(limitations)),
        analysis_trail=(
            "Validated typed incident, evidence, and unique references.",
            "Assessed data health before interpreting business movement.",
            "Calculated absolute driver changes and signed contribution shares.",
            "Reconciled explained and unexplained movement where partition-safe.",
            "Evaluated competing hypotheses and recorded falsification outcomes.",
            "Applied causal-evidence and abstention gates.",
        ),
    )


def _period_values(values: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return values.dt.strftime("%Y-%m-%d")
    if grain == "week":
        return values.dt.to_period("W").apply(
            lambda item: str(item.start_time.date()) if not pd.isna(item) else None
        )
    frequency = {"month": "M", "quarter": "Q", "year": "Y"}[grain]
    return values.dt.to_period(frequency).astype(str)


def _next_evidence_id(existing: set[str]) -> str:
    number = 1
    while f"E{number}" in existing:
        number += 1
    value = f"E{number}"
    existing.add(value)
    return value


def _source_evidence(items: Iterable[RCAEvidence | Mapping[str, object]]) -> list[RCAEvidence]:
    """Normalize existing workflow evidence without depending on its contract."""

    normalized: list[RCAEvidence] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, RCAEvidence):
            normalized.append(item)
            continue
        evidence_id = str(item.get("evidence_id") or f"E{index}")
        normalized.append(
            RCAEvidence(
                evidence_id=evidence_id,
                source_id=str(item.get("operation_id") or item.get("source_id") or "workflow"),
                description=str(item.get("title") or item.get("description") or "Workflow evidence"),
                quality=str(item.get("quality_status") or item.get("quality") or "caution"),
                evidence_type=str(item.get("evidence_type") or "descriptive"),
            )
        )
    return normalized


def investigate_dataframe(
    frame: pd.DataFrame,
    semantic_definition: RCASemanticDefinition,
    *,
    source_evidence: Iterable[RCAEvidence | Mapping[str, object]] = (),
    state: Mapping[str, object] | None = None,
) -> RCAInvestigationReport:
    """Build and run an RCA request directly from a cleaned dataframe.

    Runtime integration inputs are intentionally small: the cleaned frame, a
    semantic definition naming one additive metric/time/driver relationship,
    optional existing evidence, and optional state containing explicit
    ``baseline_period``, ``comparison_period``, ``period_completeness_confirmed``
    and typed ``root_cause_hypotheses``.  The function has no database or LLM
    dependency.
    """

    definition = RCASemanticDefinition.model_validate(semantic_definition)
    state = state or {}
    required = {definition.metric_column, definition.time_column, definition.driver_column}
    missing = sorted(required - {str(column) for column in frame.columns})
    if missing:
        raise ValueError(f"Root-cause semantic definition references missing columns: {missing}")
    if not pd.api.types.is_numeric_dtype(frame[definition.metric_column]):
        raise ValueError(f"Root-cause metric '{definition.metric_column}' must be numeric")

    try:
        parsed_time = parse_date_series(frame[definition.time_column], column_name=definition.time_column)
    except DateSemanticError as exc:
        raise ValueError(str(exc)) from exc
    metric = pd.to_numeric(frame[definition.metric_column], errors="coerce")
    valid = frame.loc[parsed_time.notna() & metric.notna(), [definition.driver_column]].copy()
    valid[definition.metric_column] = metric.loc[valid.index]
    valid["_period"] = _period_values(parsed_time.loc[valid.index], definition.time_grain)
    observed_periods = sorted(str(item) for item in valid["_period"].dropna().unique())
    if len(observed_periods) < 2:
        raise ValueError("Root-cause analysis requires at least two valid observed periods")

    context = extract_explicit_comparison_context(state)
    baseline_period = context.baseline_period if context else observed_periods[-2]
    comparison_period = context.comparison_period if context else observed_periods[-1]
    if baseline_period not in observed_periods or comparison_period not in observed_periods:
        raise ValueError("Requested RCA baseline or comparison period is not present in the data")

    imported = _source_evidence(source_evidence)
    known_ids = {item.evidence_id for item in imported}
    incident_evidence_id = _next_evidence_id(known_ids)
    driver_evidence_id = _next_evidence_id(known_ids)
    health_evidence_id = _next_evidence_id(known_ids)
    generated_evidence = [
        RCAEvidence(
            evidence_id=incident_evidence_id,
            source_id="rca:dataframe:incident",
            description=f"{definition.metric_name} comparison for {baseline_period} and {comparison_period}",
        ),
        RCAEvidence(
            evidence_id=driver_evidence_id,
            source_id="rca:dataframe:drivers",
            description=f"Additive {definition.metric_name} decomposition by {definition.driver_column}",
        ),
        RCAEvidence(
            evidence_id=health_evidence_id,
            source_id="rca:dataframe:health",
            description="Date validity, metric completeness, duplicates, and period coverage checks",
            quality="ready" if parsed_time.notna().all() and metric.notna().all() else "caution",
            evidence_type="operational",
        ),
    ]

    totals = valid.groupby("_period")[definition.metric_column].sum()
    baseline_value = float(totals.loc[baseline_period])
    comparison_value = float(totals.loc[comparison_period])
    selected = valid[valid["_period"].isin((baseline_period, comparison_period))]
    pivot = selected.groupby([definition.driver_column, "_period"], dropna=False)[definition.metric_column].sum().unstack(fill_value=0)
    drivers = tuple(
        DriverInput(
            driver_id=f"D{index}",
            name="<missing>" if pd.isna(driver_name) else str(driver_name),
            baseline_value=float(row.get(baseline_period, 0)),
            comparison_value=float(row.get(comparison_period, 0)),
            evidence_ids=(driver_evidence_id,),
        )
        for index, (driver_name, row) in enumerate(pivot.iterrows(), start=1)
    )

    date_missing = int(parsed_time.isna().sum())
    metric_missing = int(metric.isna().sum())
    duplicate_count = int(frame.duplicated().sum())
    checks = [
        DataHealthCheck(
            check_id="DH1",
            name="Valid dates",
            status="pass" if date_missing == 0 else "fail" if date_missing == len(frame) else "caution",
            blocking=date_missing == len(frame),
            detail=f"{date_missing} of {len(frame)} rows have missing or invalid dates.",
            evidence_ids=(health_evidence_id,),
        ),
        DataHealthCheck(
            check_id="DH2",
            name="Metric completeness",
            status="pass" if metric_missing == 0 else "fail" if metric_missing == len(frame) else "caution",
            blocking=metric_missing == len(frame),
            detail=f"{metric_missing} of {len(frame)} rows have missing or invalid metric values.",
            evidence_ids=(health_evidence_id,),
        ),
        DataHealthCheck(
            check_id="DH3",
            name="Exact duplicate rows",
            status="pass" if duplicate_count == 0 else "caution",
            detail=f"{duplicate_count} exact duplicate rows were observed.",
            evidence_ids=(health_evidence_id,),
        ),
    ]
    completeness = state.get("period_completeness_confirmed")
    checks.append(
        DataHealthCheck(
            check_id="DH4",
            name="Comparison-period completeness",
            status="pass" if completeness is True else "fail" if completeness is False else "unknown",
            blocking=completeness is False,
            detail=(
                "Comparison-period completeness was confirmed."
                if completeness is True
                else "Comparison period is explicitly incomplete."
                if completeness is False
                else "Comparison-period completeness has not been confirmed."
            ),
            evidence_ids=(health_evidence_id,),
        )
    )

    hypotheses = tuple(
        HypothesisInput.model_validate(item)
        for item in state.get("root_cause_hypotheses", ())  # type: ignore[arg-type]
    )
    request = RCAInvestigationRequest(
        incident=IncidentInput(
            metric=definition.metric_name,
            unit=definition.unit,
            baseline_period=baseline_period,
            comparison_period=comparison_period,
            baseline_value=baseline_value,
            comparison_value=comparison_value,
            evidence_ids=(incident_evidence_id,),
        ),
        evidence=tuple((*imported, *generated_evidence)),
        data_health_checks=tuple(checks),
        drivers=drivers,
        drivers_form_partition=True,
        hypotheses=hypotheses,
    )
    return investigate_root_cause(request)


def build_root_cause_report(
    frame: pd.DataFrame,
    semantic_definition: RCASemanticDefinition | Mapping[str, object],
    *,
    evidence: Iterable[RCAEvidence | Mapping[str, object]] = (),
    state: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """JSON-ready boundary intended for ``RootCauseAgent`` integration."""

    report = investigate_dataframe(
        frame,
        RCASemanticDefinition.model_validate(semantic_definition),
        source_evidence=evidence,
        state=state,
    )
    return report.model_dump(mode="json")


# Milestone 1: single-level investigation.  It deliberately has no recursive
# drilling, LLM planning, or causal claims.  Candidate dimensions are axes;
# the returned driver is always a specific segment inside an axis.
def _investigation_strength(share: float | None) -> str:
    """Thresholds are policy, not calibrated probabilities: >=50 strong, >=20
    moderate, >=5 weak, otherwise insufficient."""
    if share is None:
        return "insufficient"
    magnitude = abs(share)
    if magnitude >= 50:
        return "strong"
    if magnitude >= 20:
        return "moderate"
    if magnitude >= 5:
        return "weak"
    return "insufficient"


def _is_material_contribution(share: float | None, threshold: float) -> bool:
    return share is not None and abs(share) >= threshold


def _normalized_dimension_values(values: pd.Series) -> pd.Series:
    """Keep missing or blank segments in an additive partition."""
    as_text = values.astype("string")
    missing = values.isna() | as_text.str.strip().eq("")
    return as_text.mask(missing, "__MISSING__")


def _safe_period_frame(
    frame: pd.DataFrame, request: SingleLevelInvestigationRequest
) -> tuple[pd.DataFrame, list[InvestigationHealthCheck], list[InvestigationEvidence]]:
    kpi = request.kpi
    missing = [column for column in (kpi.metric_column, kpi.time_column, *request.candidate_dimensions) if column not in frame]
    if missing:
        evidence = InvestigationEvidence(
            evidence_id="IE1", kind="data_health", description="Required investigation fields are missing.",
            values={"missing_columns": ", ".join(missing)},
        )
        check = InvestigationHealthCheck(
            check_id="IQ1", name="Required fields", status="fail", blocking=True,
            detail=f"Missing required columns: {', '.join(missing)}.", evidence_id="IE1",
        )
        return frame.iloc[0:0].copy(), [check], [evidence]
    try:
        parsed = parse_date_series(frame[kpi.time_column], column_name=kpi.time_column)
    except DateSemanticError as error:
        evidence = InvestigationEvidence(evidence_id="IE1", kind="data_health", description="Date parsing failed.", values={"error": str(error)})
        check = InvestigationHealthCheck(check_id="IQ1", name="Valid dates", status="fail", blocking=True, detail=str(error), evidence_id="IE1")
        return frame.iloc[0:0].copy(), [check], [evidence]
    result = frame.copy()
    result["_investigation_period"] = _period_values(parsed, kpi.time_grain)
    result["_investigation_metric"] = pd.to_numeric(result[kpi.metric_column], errors="coerce")
    baseline_rows = result[result["_investigation_period"] == request.baseline_period]
    current_rows = result[result["_investigation_period"] == request.comparison_period]
    checks: list[InvestigationHealthCheck] = []
    evidence: list[InvestigationEvidence] = []
    def add(name: str, status: str, blocking: bool, detail: str, values: dict[str, float | int | str | None]) -> None:
        evidence_id = f"IE{len(evidence) + 1}"
        evidence.append(InvestigationEvidence(evidence_id=evidence_id, kind="data_health", description=detail, values=values))
        checks.append(InvestigationHealthCheck(check_id=f"IQ{len(checks) + 1}", name=name, status=status, blocking=blocking, detail=detail, evidence_id=evidence_id))
    add("Requested periods present", "pass" if len(baseline_rows) and len(current_rows) else "fail", not (len(baseline_rows) and len(current_rows)),
        f"Baseline rows: {len(baseline_rows)}; comparison rows: {len(current_rows)}.", {"baseline_rows": len(baseline_rows), "comparison_rows": len(current_rows)})
    if len(baseline_rows) and len(current_rows):
        coverage = len(current_rows) / len(baseline_rows)
        add("Comparison row coverage", "pass" if coverage >= request.comparison_coverage_ratio else "fail", coverage < request.comparison_coverage_ratio,
            f"Comparison row coverage is {coverage:.3f}; required minimum is {request.comparison_coverage_ratio:.3f}.", {"coverage_ratio": coverage})
        null_rate = float(current_rows["_investigation_metric"].isna().mean())
        add("Comparison metric completeness", "pass" if null_rate <= request.maximum_current_metric_null_pct else "fail", null_rate > request.maximum_current_metric_null_pct,
            f"Comparison metric null rate is {null_rate:.3f}; allowed maximum is {request.maximum_current_metric_null_pct:.3f}.", {"comparison_metric_null_rate": null_rate})
    return result, checks, evidence


def run_single_level_investigation(
    frame: pd.DataFrame, request: SingleLevelInvestigationRequest | Mapping[str, object]
) -> InvestigationState:
    """Run the smallest real deterministic KPI investigation loop."""
    request = SingleLevelInvestigationRequest.model_validate(request)
    if request.evidence_driven_control_enabled:
        return run_evidence_driven_investigation(frame, request)
    if request.hypothesis_planning_enabled:
        return run_hypothesis_planned_investigation(frame, request)
    if request.maximum_depth > 1:
        return run_recursive_investigation(frame, request)
    prepared, health, evidence = _safe_period_frame(frame, request)
    hypotheses = [InvestigationHypothesis(hypothesis_id=f"IH{i}", dimension=dimension, statement=f"{dimension} contains a material segment contributor.") for i, dimension in enumerate(request.candidate_dimensions, 1)]
    blocked = any(check.blocking and check.status == "fail" for check in health)
    if blocked:
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi,
            baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions,
            outcome="data_quality_incident", data_health=tuple(health), hypotheses=tuple(hypotheses), evidence=tuple(evidence),
            stopping_reason="A blocking data-quality check failed before contribution analysis.")
    selected = prepared[prepared["_investigation_period"].isin((request.baseline_period, request.comparison_period))].copy()
    selected = selected[selected["_investigation_metric"].notna()]
    totals = selected.groupby("_investigation_period")["_investigation_metric"].sum()
    baseline = float(totals.get(request.baseline_period, 0.0))
    comparison = float(totals.get(request.comparison_period, 0.0))
    net = comparison - baseline
    incident_id = f"IE{len(evidence) + 1}"
    evidence.append(InvestigationEvidence(evidence_id=incident_id, kind="incident", description=f"{request.kpi.metric_name} moved from {baseline:g} to {comparison:g}.", values={"baseline_value": baseline, "comparison_value": comparison, "net_kpi_movement": net}))
    if net == 0:
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="inconclusive", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=net, data_health=tuple(health), hypotheses=tuple(hypotheses), evidence=tuple(evidence), stopping_reason="The KPI has no net movement in the requested comparison.")
    tests: list[DimensionContributionTest] = []
    candidates: list[tuple[SegmentContribution, str, str]] = []
    for index, dimension in enumerate(request.candidate_dimensions, 1):
        partition = selected.copy()
        partition["_investigation_segment"] = _normalized_dimension_values(partition[dimension])
        pivot = partition.groupby(["_investigation_segment", "_investigation_period"], dropna=False)["_investigation_metric"].sum().unstack(fill_value=0)
        contributions: list[SegmentContribution] = []
        for segment, row in pivot.iterrows():
            before, after = float(row.get(request.baseline_period, 0)), float(row.get(request.comparison_period, 0))
            change = after - before
            share = change / net * 100
            aligned = change * net > 0
            direction = "with_incident" if aligned else "positive_offset" if change * net < 0 else "neutral"
            item = SegmentContribution(dimension=dimension, segment="<missing>" if pd.isna(segment) else str(segment), baseline_value=before, comparison_value=after, signed_change=change, contribution_to_net_change_pct=share, direction=direction)
            contributions.append(item)
            if aligned:
                candidates.append((item, dimension, f"IE{len(evidence) + 1}"))
        negative = sum(item.signed_change for item in contributions if item.signed_change < 0)
        positive = sum(item.signed_change for item in contributions if item.signed_change > 0)
        dim_net = sum(item.signed_change for item in contributions)
        evidence_id = f"IE{len(evidence) + 1}"
        evidence.append(InvestigationEvidence(evidence_id=evidence_id, test_id=f"IT{index}", kind="dimension_contribution", description=f"Signed additive contribution test for {dimension}.", dimension=dimension, values={"negative_pressure": negative, "positive_offset": positive, "net_dimension_change": dim_net, "net_kpi_movement": net}))
        tests.append(DimensionContributionTest(test_id=f"IT{index}", dimension=dimension, status="completed", evidence_id=evidence_id, segment_contributions=tuple(contributions), negative_pressure=negative, positive_offset=positive, net_dimension_change=dim_net, reconciles_to_kpi_change=abs(dim_net-net) < 1e-9))
    candidates.sort(key=lambda item: (-abs(item[0].signed_change), item[0].dimension, item[0].segment))
    best = candidates[0][0] if candidates else None
    updated: list[InvestigationHypothesis] = []
    for hypothesis in hypotheses:
        test = next(test for test in tests if test.dimension == hypothesis.dimension)
        local = [item for item in test.segment_contributions if item.direction == "with_incident"]
        local.sort(key=lambda item: (-abs(item.signed_change), item.segment))
        lead = local[0] if local else None
        strength = _investigation_strength(lead.contribution_to_net_change_pct if lead else None)
        status = "supported" if strength in {"strong", "moderate"} else "weak" if strength == "weak" else "rejected"
        updated.append(InvestigationHypothesis(hypothesis_id=hypothesis.hypothesis_id, dimension=hypothesis.dimension, statement=hypothesis.statement, status=status, leading_segment=lead.segment if lead else None, signed_contribution=lead.signed_change if lead else None, contribution_to_net_change_pct=lead.contribution_to_net_change_pct if lead else None, evidence_strength=strength, evidence_ids=(test.evidence_id,), rationale=(f"{lead.segment} has signed movement {lead.signed_change:g} ({lead.contribution_to_net_change_pct:.1f}% of net KPI movement)." if lead else "No segment moved in the KPI incident direction.")))
    if (
        best is None
        or not _is_material_contribution(best.contribution_to_net_change_pct, request.material_contribution_pct)
        or _investigation_strength(best.contribution_to_net_change_pct) not in {"strong", "moderate"}
    ):
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="inconclusive", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=net, data_health=tuple(health), hypotheses=tuple(updated), tests_executed=tuple(tests), evidence=tuple(evidence), evidence_strength="insufficient" if best is None else _investigation_strength(best.contribution_to_net_change_pct), stopping_reason="No tested segment supplied a material aligned contribution.")
    winner_test = next(test for test in tests if test.dimension == best.dimension)
    return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="strongest_supported_driver", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=net, data_health=tuple(health), hypotheses=tuple(updated), tests_executed=tuple(tests), evidence=tuple(evidence), leading_dimension=best.dimension, leading_segment=best.segment, leading_signed_contribution=best.signed_change, leading_contribution_to_net_change_pct=best.contribution_to_net_change_pct, downward_pressure=winner_test.negative_pressure, positive_offset=winner_test.positive_offset, explained_movement=best.signed_change, unexplained_movement=net-best.signed_change, evidence_strength=_investigation_strength(best.contribution_to_net_change_pct), stopping_reason="A material segment contribution was identified; causal attribution remains outside this milestone.")


def _filter_to_path(frame: pd.DataFrame, path: list[InvestigationFilter]) -> pd.DataFrame:
    scoped = frame
    for item in path:
        scoped = scoped[_normalized_dimension_values(scoped[item.dimension]) == item.segment]
    return scoped


def _append_scoped_health(
    scope: pd.DataFrame,
    request: SingleLevelInvestigationRequest,
    evidence: list[InvestigationEvidence],
) -> tuple[InvestigationHealthCheck, ...]:
    """Re-run observable completeness checks after each scope restriction."""
    baseline = scope[scope["_investigation_period"] == request.baseline_period]
    comparison = scope[scope["_investigation_period"] == request.comparison_period]
    checks: list[InvestigationHealthCheck] = []

    def add(name: str, status: str, blocking: bool, detail: str, values: dict[str, float | int | str | None]) -> None:
        evidence_id = f"IE{len(evidence) + 1}"
        evidence.append(InvestigationEvidence(evidence_id=evidence_id, kind="data_health", description=detail, values=values))
        checks.append(InvestigationHealthCheck(check_id=f"IQ{len(evidence)}", name=name, status=status, blocking=blocking, detail=detail, evidence_id=evidence_id))

    periods_present = bool(len(baseline) and len(comparison))
    add("Scoped requested periods present", "pass" if periods_present else "fail", not periods_present,
        f"Scoped baseline rows: {len(baseline)}; scoped comparison rows: {len(comparison)}.",
        {"baseline_rows": len(baseline), "comparison_rows": len(comparison)})
    if periods_present:
        coverage = len(comparison) / len(baseline)
        add("Scoped comparison row coverage", "pass" if coverage >= request.comparison_coverage_ratio else "fail", coverage < request.comparison_coverage_ratio,
            f"Scoped comparison row coverage is {coverage:.3f}; required minimum is {request.comparison_coverage_ratio:.3f}.", {"coverage_ratio": coverage})
        null_rate = float(comparison["_investigation_metric"].isna().mean())
        add("Scoped comparison metric completeness", "pass" if null_rate <= request.maximum_current_metric_null_pct else "fail", null_rate > request.maximum_current_metric_null_pct,
            f"Scoped comparison metric null rate is {null_rate:.3f}; allowed maximum is {request.maximum_current_metric_null_pct:.3f}.", {"comparison_metric_null_rate": null_rate})
    return tuple(checks)


def _scoped_dimension_tests(
    scope: pd.DataFrame,
    dimensions: tuple[str, ...],
    request: SingleLevelInvestigationRequest,
    parent_movement: float,
    global_movement: float,
    evidence: list[InvestigationEvidence],
    test_start: int,
    filter_path: list[InvestigationFilter],
) -> tuple[list[DimensionContributionTest], list[SegmentContribution]]:
    valid = scope[
        scope["_investigation_period"].isin((request.baseline_period, request.comparison_period))
        & scope["_investigation_metric"].notna()
    ].copy()
    tests: list[DimensionContributionTest] = []
    aligned: list[SegmentContribution] = []
    scope_label = " > ".join(f"{item.dimension}={item.segment}" for item in filter_path) or "global"
    for index, dimension in enumerate(dimensions, start=test_start):
        partition = valid.copy()
        partition["_investigation_segment"] = _normalized_dimension_values(partition[dimension])
        pivot = partition.groupby(["_investigation_segment", "_investigation_period"], dropna=False)["_investigation_metric"].sum().unstack(fill_value=0)
        contributions: list[SegmentContribution] = []
        for segment, row in pivot.iterrows():
            before = float(row.get(request.baseline_period, 0.0))
            after = float(row.get(request.comparison_period, 0.0))
            change = after - before
            local_share = change / parent_movement * 100
            direction = "with_incident" if change * parent_movement > 0 else "positive_offset" if change * parent_movement < 0 else "neutral"
            item = SegmentContribution(dimension=dimension, segment=str(segment), baseline_value=before, comparison_value=after, signed_change=change, contribution_to_net_change_pct=local_share, direction=direction)
            contributions.append(item)
            if direction == "with_incident":
                aligned.append(item)
        negative = sum(item.signed_change for item in contributions if item.signed_change < 0)
        positive = sum(item.signed_change for item in contributions if item.signed_change > 0)
        net = sum(item.signed_change for item in contributions)
        evidence_id = f"IE{len(evidence) + 1}"
        test_id = f"IT{index}"
        evidence.append(InvestigationEvidence(evidence_id=evidence_id, test_id=test_id, kind="dimension_contribution", description=f"Signed additive contribution test for {dimension} within {scope_label}.", dimension=dimension, values={"parent_kpi_movement": parent_movement, "global_kpi_movement": global_movement, "negative_pressure": negative, "positive_offset": positive, "net_dimension_change": net, "scope": scope_label}))
        tests.append(DimensionContributionTest(test_id=test_id, dimension=dimension, status="completed", evidence_id=evidence_id, segment_contributions=tuple(contributions), negative_pressure=negative, positive_offset=positive, net_dimension_change=net, reconciles_to_kpi_change=abs(net - parent_movement) <= request.negligible_parent_movement_tolerance))
    return tests, aligned


def _test_hypothesis_status(test: DimensionContributionTest, threshold: float) -> str:
    aligned = [item for item in test.segment_contributions if item.direction == "with_incident"]
    if not aligned:
        return "rejected"
    share = max(abs(item.contribution_to_net_change_pct or 0.0) for item in aligned)
    return "supported" if share >= threshold else "weak" if share >= 5 else "rejected"


def _verified_test_summaries(
    tests: list[DimensionContributionTest], threshold: float
) -> tuple[dict[str, object], ...]:
    summaries: list[dict[str, object]] = []
    for test in tests:
        aligned = [item for item in test.segment_contributions if item.direction == "with_incident"]
        aligned.sort(key=lambda item: (-abs(item.signed_change), item.segment))
        lead = aligned[0] if aligned else None
        summaries.append({
            "dimension": test.dimension,
            "status": _test_hypothesis_status(test, threshold),
            "leading_segment": lead.segment if lead else None,
            "signed_contribution": lead.signed_change if lead else None,
            "local_contribution_pct": lead.contribution_to_net_change_pct if lead else None,
            "evidence_strength": _investigation_strength(lead.contribution_to_net_change_pct if lead else None),
            "test_id": test.test_id,
            "evidence_id": test.evidence_id,
        })
    return tuple(summaries)


def _successful_test_ceiling(dimension_count: int, maximum_depth: int) -> int:
    """n + (n-1) + ... for the permitted greedy single-path scopes."""
    return sum(dimension_count - depth for depth in range(min(dimension_count, maximum_depth)))


def _leading_contributor(
    tests: list[DimensionContributionTest], threshold: float
) -> tuple[SegmentContribution | None, DimensionContributionTest | None]:
    candidates = [
        (segment, test)
        for test in tests
        for segment in test.segment_contributions
        if segment.direction == "with_incident"
    ]
    candidates.sort(key=lambda item: (-abs(item[0].signed_change), item[0].dimension, item[0].segment))
    if not candidates:
        return None, None
    best, test = candidates[0]
    if not _is_material_contribution(best.contribution_to_net_change_pct, threshold):
        return None, None
    if _investigation_strength(best.contribution_to_net_change_pct) not in {"strong", "moderate"}:
        return None, None
    return best, test


def _root_hypotheses(
    dimensions: tuple[str, ...], tests: list[DimensionContributionTest]
) -> tuple[InvestigationHypothesis, ...]:
    by_dimension = {test.dimension: test for test in tests}
    hypotheses: list[InvestigationHypothesis] = []
    for index, dimension in enumerate(dimensions, 1):
        test = by_dimension.get(dimension)
        if test is None:
            hypotheses.append(InvestigationHypothesis(hypothesis_id=f"IH{index}", dimension=dimension, statement=f"{dimension} contains a material segment contributor.", status="unresolved", rationale="The approved dimension was not successfully tested."))
            continue
        aligned = [item for item in test.segment_contributions if item.direction == "with_incident"]
        aligned.sort(key=lambda item: (-abs(item.signed_change), item.segment))
        lead = aligned[0] if aligned else None
        strength = _investigation_strength(lead.contribution_to_net_change_pct if lead else None)
        status = "supported" if strength in {"strong", "moderate"} else "weak" if strength == "weak" else "rejected"
        hypotheses.append(InvestigationHypothesis(hypothesis_id=f"IH{index}", dimension=dimension, statement=f"{dimension} contains a material segment contributor.", status=status, leading_segment=lead.segment if lead else None, signed_contribution=lead.signed_change if lead else None, contribution_to_net_change_pct=lead.contribution_to_net_change_pct if lead else None, evidence_strength=strength, evidence_ids=(test.evidence_id,), rationale=(f"{lead.segment} is the leading aligned segment in the deterministic test." if lead else "No segment moved with the incident.")))
    return tuple(hypotheses)


def run_evidence_driven_investigation(
    frame: pd.DataFrame, request: SingleLevelInvestigationRequest
) -> InvestigationState:
    """Run a bounded THINK -> one deterministic test -> OBSERVE loop."""
    request = SingleLevelInvestigationRequest.model_validate(request)
    prepared, health, evidence = _safe_period_frame(frame, request)
    empty_hypotheses = tuple(InvestigationHypothesis(hypothesis_id=f"IH{i}", dimension=dimension, statement=f"{dimension} contains a material segment contributor.") for i, dimension in enumerate(request.candidate_dimensions, 1))
    if any(check.blocking and check.status == "fail" for check in health):
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="data_quality_incident", data_health=tuple(health), hypotheses=empty_hypotheses, evidence=tuple(evidence), stopping_reason="A blocking data-quality check failed before controlled investigation.")
    selected = prepared[prepared["_investigation_period"].isin((request.baseline_period, request.comparison_period)) & prepared["_investigation_metric"].notna()]
    totals = selected.groupby("_investigation_period")["_investigation_metric"].sum()
    baseline = float(totals.get(request.baseline_period, 0.0))
    comparison = float(totals.get(request.comparison_period, 0.0))
    global_movement = comparison - baseline
    evidence.append(InvestigationEvidence(evidence_id=f"IE{len(evidence) + 1}", kind="incident", description=f"{request.kpi.metric_name} moved from {baseline:g} to {comparison:g}.", values={"baseline_value": baseline, "comparison_value": comparison, "net_kpi_movement": global_movement}))
    if abs(global_movement) <= request.negligible_parent_movement_tolerance:
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="inconclusive", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=global_movement, data_health=tuple(health), hypotheses=empty_hypotheses, evidence=tuple(evidence), stopping_reason="The KPI movement is numerically negligible.")

    schema = tuple((str(column), str(dtype)) for column, dtype in frame.dtypes.items())
    all_tests: list[DimensionContributionTest] = []
    planning_records: list[HypothesisPlanningRecord] = []
    iterations: list[InvestigationIteration] = []
    executed_registry: set[tuple[tuple[tuple[str, str], ...], str]] = set()
    ceiling = _successful_test_ceiling(len(request.candidate_dimensions), request.maximum_depth)

    def run_scope(
        scope: pd.DataFrame,
        filter_path: tuple[InvestigationFilter, ...],
        dimensions: tuple[str, ...],
        parent_movement: float,
        node_id: str,
    ) -> tuple[list[DimensionContributionTest], HypothesisPlanningRecord]:
        record = plan_hypotheses(request, schema=schema, filter_path=filter_path, allowed_dimensions=dimensions, planning_id=len(planning_records) + 1)
        planning_records.append(record)
        scope_tests: list[DimensionContributionTest] = []
        tested: list[str] = []
        priority_order = tuple(item.target_dimension for item in sorted(record.validated_proposals, key=lambda item: item.priority))
        while True:
            available = tuple(dimension for dimension in priority_order if dimension not in tested)
            if not available:
                break
            if len(all_tests) >= ceiling:
                raise RuntimeError("Derived successful-test ceiling would be exceeded")
            known_ids = tuple(test.test_id for test in scope_tests)
            decision = choose_next_action(request, filter_path=filter_path, available_dimensions=available, tested_dimensions=tuple(tested), planning_record=record, verified_results=_verified_test_summaries(scope_tests, request.material_contribution_pct), remaining_iteration_budget=ceiling - len(all_tests))
            dimension = decision.executed_dimension
            if decision.executed_action != "test_dimension" or dimension is None:
                break
            identity = (tuple((item.dimension, item.segment) for item in filter_path), dimension)
            if identity in executed_registry:
                raise RuntimeError("Duplicate scope/dimension execution was blocked")
            before_evidence = len(evidence)
            new_tests, _ = _scoped_dimension_tests(scope, (dimension,), request, parent_movement, global_movement, evidence, len(all_tests) + 1, list(filter_path))
            test = new_tests[0]
            executed_registry.add(identity)
            scope_tests.append(test)
            all_tests.append(test)
            tested.append(dimension)
            record = update_hypothesis_statuses(record, (test,), material_contribution_pct=request.material_contribution_pct)
            planning_records[-1] = record
            status = _test_hypothesis_status(test, request.material_contribution_pct)
            iterations.append(InvestigationIteration(iteration_id=f"II{len(iterations) + 1}", scope_node_id=node_id, filter_path=filter_path, available_dimensions=available, tested_dimensions_before=tuple(tested[:-1]), known_test_ids=known_ids, requested_action=decision.proposal.action if decision.proposal else None, requested_dimension=decision.proposal.target_dimension if decision.proposal else None, executed_action="test_dimension", executed_dimension=dimension, decision_source=decision.decision_source, validation_status=decision.validation_status, rejection_reason=decision.rejection_reason, controller_reason_code=decision.proposal.reason_code if decision.proposal else None, fallback_used=decision.fallback_used, test_id=test.test_id, evidence_id=test.evidence_id, resulting_hypothesis_status=status, iteration_outcome="test_executed", continue_reason=("Eligible dimensions remain in this scope." if len(tested) < len(priority_order) else "All eligible dimensions in this scope are now tested.")))
            if len(evidence) != before_evidence + 1:
                raise RuntimeError("A controller iteration must create exactly one dimension-test evidence record")
        return scope_tests, record

    root_tests, _ = run_scope(prepared, (), request.candidate_dimensions, global_movement, "IN0")
    if len(root_tests) != len(request.candidate_dimensions) or any(not test.reconciles_to_kpi_change for test in root_tests):
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="inconclusive", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=global_movement, data_health=tuple(health), hypotheses=_root_hypotheses(request.candidate_dimensions, root_tests), tests_executed=tuple(all_tests), evidence=tuple(evidence), stopping_reason="Controlled root scope did not achieve deterministic analytical sufficiency.", hypothesis_planning_records=tuple(planning_records), investigation_iterations=tuple(iterations))
    best, winner_test = _leading_contributor(root_tests, request.material_contribution_pct)
    root_node = InvestigationPathNode(node_id="IN0", depth=0, filter_path=(), segment_movement=global_movement, remaining_dimensions=request.candidate_dimensions, tested_dimensions=tuple(test.dimension for test in root_tests), test_ids=tuple(test.test_id for test in root_tests), evidence_ids=tuple(test.evidence_id for test in root_tests), data_health=tuple(health), evidence_strength=_investigation_strength(best.contribution_to_net_change_pct if best else None))
    if best is None or winner_test is None:
        return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="inconclusive", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=global_movement, data_health=tuple(health), hypotheses=_root_hypotheses(request.candidate_dimensions, root_tests), tests_executed=tuple(all_tests), evidence=tuple(evidence), evidence_strength="insufficient", stopping_reason="No tested segment supplied a material aligned contribution.", investigation_path=(root_node,), hypothesis_planning_records=tuple(planning_records), investigation_iterations=tuple(iterations))

    path = [InvestigationFilter(dimension=best.dimension, segment=best.segment)]
    nodes = [root_node, InvestigationPathNode(node_id="IN1", depth=1, parent_node_id="IN0", filter_path=tuple(path), selected_dimension=best.dimension, selected_segment=best.segment, parent_kpi_movement=global_movement, segment_movement=best.signed_change, local_contribution_pct=best.contribution_to_net_change_pct, global_contribution_pct=best.contribution_to_net_change_pct, remaining_dimensions=tuple(dimension for dimension in request.candidate_dimensions if dimension != best.dimension), evidence_ids=(winner_test.evidence_id,), evidence_strength=_investigation_strength(best.contribution_to_net_change_pct))]
    while True:
        node = nodes[-1]
        reason: str | None = None
        if node.depth >= request.maximum_depth:
            reason = "maximum_depth_reached"
        elif not node.remaining_dimensions:
            reason = "no_dimensions_remaining"
        elif node.segment_movement is None or abs(node.segment_movement) <= request.negligible_parent_movement_tolerance:
            reason = "negligible_parent_movement"
        if reason:
            nodes[-1] = node.model_copy(update={"stopping_reason": reason})
            break
        scoped = _filter_to_path(prepared, path)
        before_health = len(evidence)
        scoped_health = _append_scoped_health(scoped, request, evidence)
        health_ids = tuple(item.evidence_id for item in evidence[before_health:])
        if any(check.blocking and check.status == "fail" for check in scoped_health):
            nodes[-1] = node.model_copy(update={"data_health": scoped_health, "evidence_ids": tuple(dict.fromkeys((*node.evidence_ids, *health_ids))), "stopping_reason": "scoped_data_quality_failure"})
            break
        baseline_rows = scoped[(scoped["_investigation_period"] == request.baseline_period) & scoped["_investigation_metric"].notna()]
        comparison_rows = scoped[(scoped["_investigation_period"] == request.comparison_period) & scoped["_investigation_metric"].notna()]
        if min(len(baseline_rows), len(comparison_rows)) < request.minimum_rows_per_period_for_drill_down:
            nodes[-1] = node.model_copy(update={"data_health": scoped_health, "evidence_ids": tuple(dict.fromkeys((*node.evidence_ids, *health_ids))), "stopping_reason": "insufficient_rows"})
            break
        scope_tests, _ = run_scope(scoped, tuple(path), node.remaining_dimensions, float(node.segment_movement), node.node_id)
        nodes[-1] = node.model_copy(update={"data_health": scoped_health, "tested_dimensions": tuple(test.dimension for test in scope_tests), "test_ids": tuple(test.test_id for test in scope_tests), "evidence_ids": tuple(dict.fromkeys((*node.evidence_ids, *health_ids, *(test.evidence_id for test in scope_tests))))})
        if len(scope_tests) != len(node.remaining_dimensions) or any(not test.reconciles_to_kpi_change for test in scope_tests):
            nodes[-1] = nodes[-1].model_copy(update={"stopping_reason": "reconciliation_failure"})
            break
        child, child_test = _leading_contributor(scope_tests, request.material_contribution_pct)
        if child is None or child_test is None:
            aligned_exists = any(segment.direction == "with_incident" for test in scope_tests for segment in test.segment_contributions)
            nodes[-1] = nodes[-1].model_copy(update={"stopping_reason": "no_material_child_contributor" if aligned_exists else "no_aligned_child_contributor"})
            break
        path.append(InvestigationFilter(dimension=child.dimension, segment=child.segment))
        depth = node.depth + 1
        global_share = child.signed_change / global_movement * 100
        nodes.append(InvestigationPathNode(node_id=f"IN{depth}", depth=depth, parent_node_id=node.node_id, filter_path=tuple(path), selected_dimension=child.dimension, selected_segment=child.segment, parent_kpi_movement=node.segment_movement, segment_movement=child.signed_change, local_contribution_pct=child.contribution_to_net_change_pct, global_contribution_pct=global_share, remaining_dimensions=tuple(dimension for dimension in node.remaining_dimensions if dimension != child.dimension), evidence_ids=(child_test.evidence_id,), evidence_strength=_investigation_strength(child.contribution_to_net_change_pct)))

    if len(all_tests) > ceiling:
        raise RuntimeError("Controlled investigation exceeded its derived test ceiling")
    return InvestigationState(investigation_id=request.investigation_id, goal=request.goal, kpi=request.kpi, baseline_period=request.baseline_period, comparison_period=request.comparison_period, candidate_dimensions=request.candidate_dimensions, outcome="strongest_supported_driver", baseline_value=baseline, comparison_value=comparison, net_kpi_movement=global_movement, data_health=tuple(health), hypotheses=_root_hypotheses(request.candidate_dimensions, root_tests), tests_executed=tuple(all_tests), evidence=tuple(evidence), leading_dimension=best.dimension, leading_segment=best.segment, leading_signed_contribution=best.signed_change, leading_contribution_to_net_change_pct=best.contribution_to_net_change_pct, downward_pressure=winner_test.negative_pressure, positive_offset=winner_test.positive_offset, explained_movement=best.signed_change, unexplained_movement=global_movement-best.signed_change, evidence_strength=_investigation_strength(best.contribution_to_net_change_pct), stopping_reason=nodes[-1].stopping_reason or "Controlled investigation completed.", investigation_path=tuple(nodes), hypothesis_planning_records=tuple(planning_records), investigation_iterations=tuple(iterations))


def run_hypothesis_planned_investigation(
    frame: pd.DataFrame, request: SingleLevelInvestigationRequest
) -> InvestigationState:
    """Add bounded dimension ordering without letting an LLM affect evidence."""
    schema = tuple((str(column), str(dtype)) for column, dtype in frame.dtypes.items())
    records: list[HypothesisPlanningRecord] = []

    def plan_scope(
        filter_path: tuple[InvestigationFilter, ...], allowed_dimensions: tuple[str, ...]
    ) -> tuple[tuple[str, ...], HypothesisPlanningRecord]:
        # History is intentionally keyed by the exact analytical population.
        previously_tested = tuple(
            proposal.target_dimension
            for record in records
            if record.filter_path == filter_path
            for proposal in record.validated_proposals
            if proposal.status in {"supported", "weak", "rejected"}
        )
        record = plan_hypotheses(
            request,
            schema=schema,
            filter_path=filter_path,
            allowed_dimensions=allowed_dimensions,
            already_tested_dimensions=previously_tested,
            planning_id=len(records) + 1,
        )
        return tuple(item.target_dimension for item in record.validated_proposals), record

    root_order, root_record = plan_scope((), request.candidate_dimensions)
    records.append(root_record)
    deterministic_request = request.model_copy(
        update={"candidate_dimensions": root_order, "hypothesis_planning_enabled": False}
    )
    if deterministic_request.maximum_depth > 1:
        result = run_recursive_investigation(
            frame,
            deterministic_request,
            planning_callback=plan_scope,
            planning_records=records,
        )
    else:
        result = run_single_level_investigation(frame, deterministic_request)
    records[0] = update_hypothesis_statuses(root_record, result.tests_executed[:len(root_order)], material_contribution_pct=request.material_contribution_pct)
    return result.model_copy(update={"hypothesis_planning_records": tuple(records)})


def run_recursive_investigation(
    frame: pd.DataFrame,
    request: SingleLevelInvestigationRequest | Mapping[str, object],
    *,
    planning_callback: Callable[[tuple[InvestigationFilter, ...], tuple[str, ...]], tuple[tuple[str, ...], HypothesisPlanningRecord]] | None = None,
    planning_records: list[HypothesisPlanningRecord] | None = None,
) -> InvestigationState:
    """Greedily follow one deterministic, evidence-preserving drill-down path."""
    request = SingleLevelInvestigationRequest.model_validate(request)
    if request.maximum_depth <= 1:
        return run_single_level_investigation(frame, request.model_copy(update={"maximum_depth": 1}))
    root = run_single_level_investigation(frame, request.model_copy(update={"maximum_depth": 1}))
    root_node = InvestigationPathNode(node_id="IN0", depth=0, filter_path=(), parent_kpi_movement=None, segment_movement=root.net_kpi_movement, remaining_dimensions=request.candidate_dimensions, tested_dimensions=tuple(test.dimension for test in root.tests_executed), test_ids=tuple(test.test_id for test in root.tests_executed), evidence_ids=tuple(item.evidence_id for item in root.evidence), data_health=root.data_health, evidence_strength=root.evidence_strength)
    if root.outcome != "strongest_supported_driver":
        return root.model_copy(update={"investigation_path": (root_node,)})

    prepared, _, _ = _safe_period_frame(frame, request)
    evidence = list(root.evidence)
    all_tests = list(root.tests_executed)
    path = [InvestigationFilter(dimension=str(root.leading_dimension), segment=str(root.leading_segment))]
    current = InvestigationPathNode(node_id="IN1", depth=1, parent_node_id="IN0", filter_path=tuple(path), selected_dimension=root.leading_dimension, selected_segment=root.leading_segment, parent_kpi_movement=root.net_kpi_movement, segment_movement=root.leading_signed_contribution, local_contribution_pct=root.leading_contribution_to_net_change_pct, global_contribution_pct=root.leading_contribution_to_net_change_pct, remaining_dimensions=tuple(dimension for dimension in request.candidate_dimensions if dimension != root.leading_dimension), evidence_strength=root.evidence_strength)
    nodes: list[InvestigationPathNode] = [root_node, current]

    def stop(reason: str, *, health: tuple[InvestigationHealthCheck, ...] = (), tests: list[DimensionContributionTest] | None = None, new_evidence_ids: tuple[str, ...] = ()) -> None:
        node = nodes[-1]
        tests = tests or []
        nodes[-1] = node.model_copy(update={"data_health": health or node.data_health, "tested_dimensions": tuple(test.dimension for test in tests), "test_ids": tuple(test.test_id for test in tests), "evidence_ids": tuple(dict.fromkeys((*node.evidence_ids, *new_evidence_ids, *(test.evidence_id for test in tests)))), "stopping_reason": reason})

    while True:
        node = nodes[-1]
        if node.depth >= request.maximum_depth:
            stop("maximum_depth_reached")
            break
        if not node.remaining_dimensions:
            stop("no_dimensions_remaining")
            break
        if node.segment_movement is None or abs(node.segment_movement) <= request.negligible_parent_movement_tolerance:
            stop("negligible_parent_movement")
            break
        scoped = _filter_to_path(prepared, path)
        before_health = len(evidence)
        health = _append_scoped_health(scoped, request, evidence)
        health_evidence_ids = tuple(item.evidence_id for item in evidence[before_health:])
        if any(check.blocking and check.status == "fail" for check in health):
            stop("scoped_data_quality_failure", health=health, new_evidence_ids=health_evidence_ids)
            break
        baseline_rows = scoped[(scoped["_investigation_period"] == request.baseline_period) & scoped["_investigation_metric"].notna()]
        comparison_rows = scoped[(scoped["_investigation_period"] == request.comparison_period) & scoped["_investigation_metric"].notna()]
        if min(len(baseline_rows), len(comparison_rows)) < request.minimum_rows_per_period_for_drill_down:
            stop("insufficient_rows", health=health, new_evidence_ids=health_evidence_ids)
            break
        dimensions_to_test = node.remaining_dimensions
        record: HypothesisPlanningRecord | None = None
        if planning_callback is not None:
            dimensions_to_test, record = planning_callback(tuple(path), node.remaining_dimensions)
        tests, aligned = _scoped_dimension_tests(scoped, dimensions_to_test, request, node.segment_movement, root.net_kpi_movement or 0.0, evidence, len(all_tests) + 1, path)
        all_tests.extend(tests)
        if record is not None and planning_records is not None:
            planning_records.append(update_hypothesis_statuses(record, tests, material_contribution_pct=request.material_contribution_pct))
        if any(not test.reconciles_to_kpi_change for test in tests):
            stop("reconciliation_failure", health=health, tests=tests, new_evidence_ids=health_evidence_ids)
            break
        if not aligned:
            stop("no_aligned_child_contributor", health=health, tests=tests, new_evidence_ids=health_evidence_ids)
            break
        aligned.sort(key=lambda item: (-abs(item.signed_change), item.dimension, item.segment))
        best = aligned[0]
        strength = _investigation_strength(best.contribution_to_net_change_pct)
        if not _is_material_contribution(best.contribution_to_net_change_pct, request.material_contribution_pct) or strength not in {"strong", "moderate"}:
            stop("no_material_child_contributor", health=health, tests=tests, new_evidence_ids=health_evidence_ids)
            break
        path.append(InvestigationFilter(dimension=best.dimension, segment=best.segment))
        child_depth = node.depth + 1
        global_share = best.signed_change / root.net_kpi_movement * 100 if root.net_kpi_movement and abs(root.net_kpi_movement) > request.negligible_parent_movement_tolerance else None
        nodes[-1] = node.model_copy(update={"data_health": health, "tested_dimensions": tuple(test.dimension for test in tests), "test_ids": tuple(test.test_id for test in tests), "evidence_ids": tuple(dict.fromkeys((*node.evidence_ids, *health_evidence_ids, *(test.evidence_id for test in tests))))})
        nodes.append(InvestigationPathNode(node_id=f"IN{child_depth}", depth=child_depth, parent_node_id=node.node_id, filter_path=tuple(path), selected_dimension=best.dimension, selected_segment=best.segment, parent_kpi_movement=node.segment_movement, segment_movement=best.signed_change, local_contribution_pct=best.contribution_to_net_change_pct, global_contribution_pct=global_share, remaining_dimensions=tuple(dimension for dimension in node.remaining_dimensions if dimension != best.dimension), evidence_ids=(next(test.evidence_id for test in tests if test.dimension == best.dimension),), evidence_strength=strength))

    return root.model_copy(update={"tests_executed": tuple(all_tests), "evidence": tuple(evidence), "investigation_path": tuple(nodes), "stopping_reason": nodes[-1].stopping_reason or root.stopping_reason})
