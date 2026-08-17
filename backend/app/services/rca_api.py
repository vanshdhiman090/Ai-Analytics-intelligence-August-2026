"""Production-facing adapter around the completed V1 RCA engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd

from app.api.rca_contracts import (
    RCAConclusionV1,
    RCADataQualityIssueV1,
    RCADataQualityV1,
    RCAEvidenceV1,
    RCAExplanatoryReadinessV1,
    RCAFilterV1,
    RCAInvestigationRequestV1,
    RCAInvestigationResponseV1,
    RCAKPIMovementV1,
    RCALeadingContributorV1,
    RCAPathStepV1,
    RCARobustnessV1,
    RCATargetDecompositionV1,
)
from app.domain.root_cause_contracts import (
    DimensionContributionTest,
    InvestigationConclusion,
    InvestigationFilter,
    InvestigationHealthCheck,
    InvestigationPathNode,
    InvestigationState,
    SegmentContribution,
    SingleLevelInvestigationRequest,
)
from app.services.root_cause import run_single_level_investigation
from app.services.tabular import load_dataframe


API_MAXIMUM_DEPTH = 3
SUPPORTED_EXTENSIONS = {".csv", ".xlsx"}


class RCAAPIServiceError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        fields: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.safe_message = message
        self.fields = fields


def load_governed_dataset(dataset: Any, data_dir: Path) -> pd.DataFrame:
    """Validate a server-owned reference and load it immediately without mutation."""
    try:
        root = data_dir.resolve()
        path = Path(str(dataset.file_path)).resolve()
    except Exception as exc:
        raise RCAAPIServiceError(
            status_code=409,
            code="dataset_unavailable",
            message="The requested dataset is unavailable.",
        ) from exc
    if not path.is_relative_to(root) or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise RCAAPIServiceError(
            status_code=409,
            code="dataset_unavailable",
            message="The requested dataset is unavailable.",
        )
    if not path.is_file():
        raise RCAAPIServiceError(
            status_code=409,
            code="dataset_unavailable",
            message="The requested dataset is unavailable.",
        )
    try:
        return load_dataframe(path)
    except Exception as exc:
        raise RCAAPIServiceError(
            status_code=409,
            code="dataset_unavailable",
            message="The requested dataset could not be read.",
        ) from exc


def validate_analysis_columns(
    frame: pd.DataFrame, request: RCAInvestigationRequestV1
) -> None:
    requested = (
        request.kpi.metric_column,
        request.kpi.time_column,
        *request.candidate_dimensions,
    )
    missing = tuple(dict.fromkeys(column for column in requested if column not in frame))
    if missing:
        raise RCAAPIServiceError(
            status_code=422,
            code="invalid_analysis_definition",
            message="The RCA definition references columns that are not in the dataset.",
            fields=tuple((f"column:{column}", "column_not_found") for column in missing),
        )


def build_internal_request(
    request: RCAInvestigationRequestV1, investigation_id: UUID
) -> SingleLevelInvestigationRequest:
    """Map public semantics while keeping every RCA policy value server-owned."""
    return SingleLevelInvestigationRequest(
        investigation_id=str(investigation_id),
        goal=request.goal,
        kpi={
            "metric_name": request.kpi.name,
            "metric_column": request.kpi.metric_column,
            "time_column": request.kpi.time_column,
            "aggregation": "sum",
            "time_grain": request.kpi.time_grain,
            "unit": request.kpi.unit,
        },
        baseline_period=request.baseline_period,
        comparison_period=request.comparison_period,
        candidate_dimensions=request.candidate_dimensions,
        maximum_depth=API_MAXIMUM_DEPTH,
        hypothesis_planning_enabled=True,
        evidence_driven_control_enabled=True,
        self_falsification_enabled=True,
        conclusion_compilation_enabled=True,
    )


def _public_scope(path: tuple[InvestigationFilter, ...]) -> tuple[RCAFilterV1, ...]:
    return tuple(
        RCAFilterV1(dimension=item.dimension, segment=item.segment) for item in path
    )


@dataclass
class _EvidenceBuilder:
    items: list[RCAEvidenceV1]
    refs: dict[str, str]

    @classmethod
    def create(cls) -> "_EvidenceBuilder":
        return cls(items=[], refs={})

    def add(self, key: str, **values: Any) -> str:
        existing = self.refs.get(key)
        if existing:
            return existing
        reference = f"EV{len(self.items) + 1}"
        self.refs[key] = reference
        self.items.append(RCAEvidenceV1(evidence_ref=reference, **values))
        return reference


def _find_test_and_segment(
    state: InvestigationState,
    source: InvestigationPathNode,
    target: InvestigationPathNode,
) -> tuple[DimensionContributionTest, SegmentContribution]:
    for test in state.tests_executed:
        if test.test_id not in source.test_ids or test.dimension != target.selected_dimension:
            continue
        for segment in test.segment_contributions:
            if segment.segment == target.selected_segment and segment.direction == "with_incident":
                return test, segment
    raise RCAAPIServiceError(
        status_code=500,
        code="investigation_failed",
        message="The completed investigation could not be mapped safely.",
    )


def _prioritization_rationale(
    state: InvestigationState, target: InvestigationPathNode
) -> str | None:
    """Resolve the LLM's pre-test rationale for target's selected_dimension.

    Looks up state.hypothesis_planning_records by explicit planning_id
    equality (never by list position or call order), then requires the
    matching proposal within that record to be the LLM's own
    (source == "llm"). Null in every other case -- provider failure, the
    LLM never proposing this dimension, or deterministic_fallback having
    supplied it -- with no synthesized substitute text.
    """
    if target.planning_id is None or target.selected_dimension is None:
        return None
    record = next(
        (item for item in state.hypothesis_planning_records if item.planning_id == target.planning_id),
        None,
    )
    if record is None:
        return None
    proposal = next(
        (item for item in record.validated_proposals if item.target_dimension == target.selected_dimension),
        None,
    )
    if proposal is None or proposal.source != "llm":
        return None
    return proposal.brief_reason


def _path_projection(
    state: InvestigationState,
    conclusion: InvestigationConclusion,
    evidence: _EvidenceBuilder,
) -> tuple[
    tuple[RCAPathStepV1, ...],
    RCALeadingContributorV1 | None,
    RCATargetDecompositionV1 | None,
]:
    if not conclusion.target_scope.target_path_node_id:
        return (), None, None
    nodes = {item.node_id: item for item in state.investigation_path}
    path_ids = conclusion.conclusion_path_node_ids
    if not path_ids or path_ids[-1] != conclusion.target_scope.target_path_node_id:
        raise RCAAPIServiceError(
            status_code=500,
            code="investigation_failed",
            message="The completed investigation could not be mapped safely.",
        )
    steps: list[RCAPathStepV1] = []
    resolved: list[
        tuple[InvestigationPathNode, InvestigationPathNode, DimensionContributionTest, SegmentContribution, str]
    ] = []
    for index, node_id in enumerate(path_ids):
        node = nodes.get(node_id)
        if node is None:
            raise RCAAPIServiceError(
                status_code=500,
                code="investigation_failed",
                message="The completed investigation could not be mapped safely.",
            )
        if index == 0:
            if node.parent_node_id is not None:
                raise RCAAPIServiceError(
                    status_code=500,
                    code="investigation_failed",
                    message="The completed investigation could not be mapped safely.",
                )
            continue
        source = nodes.get(path_ids[index - 1])
        if source is None or node.parent_node_id != source.node_id:
            raise RCAAPIServiceError(
                status_code=500,
                code="investigation_failed",
                message="The completed investigation could not be mapped safely.",
            )
        test, segment = _find_test_and_segment(state, source, node)
        source_scope = _public_scope(source.filter_path)
        target_scope = _public_scope(node.filter_path)
        reference = evidence.add(
            f"contribution:{test.evidence_id}:{segment.segment}",
            kind="contribution",
            source_scope=source_scope,
            target_scope=target_scope,
            dimension=segment.dimension,
            segment=segment.segment,
            baseline_value=segment.baseline_value,
            comparison_value=segment.comparison_value,
            signed_change=segment.signed_change,
            local_contribution_pct=segment.contribution_to_net_change_pct,
            global_contribution_pct=node.global_contribution_pct,
        )
        evidence.refs.setdefault(test.evidence_id, reference)
        if node.parent_kpi_movement is None or node.segment_movement is None:
            raise RCAAPIServiceError(
                status_code=500,
                code="investigation_failed",
                message="The completed investigation could not be mapped safely.",
            )
        steps.append(
            RCAPathStepV1(
                depth=node.depth,
                source_scope=source_scope,
                target_scope=target_scope,
                dimension=segment.dimension,
                segment=segment.segment,
                baseline_value=segment.baseline_value,
                comparison_value=segment.comparison_value,
                parent_movement=node.parent_kpi_movement,
                segment_movement=node.segment_movement,
                local_contribution_pct=segment.contribution_to_net_change_pct,
                global_contribution_pct=node.global_contribution_pct,
                evidence_strength=node.evidence_strength,
                evidence_refs=(reference,),
            )
        )
        resolved.append((source, node, test, segment, reference))

    if not resolved:
        return tuple(steps), None, None
    source, target, test, segment, reference = resolved[-1]
    source_scope = _public_scope(source.filter_path)
    target_scope = _public_scope(target.filter_path)
    parent_movement = float(target.parent_kpi_movement)
    leading = RCALeadingContributorV1(
        source_scope=source_scope,
        target_scope=target_scope,
        dimension=segment.dimension,
        segment=segment.segment,
        baseline_value=segment.baseline_value,
        comparison_value=segment.comparison_value,
        signed_change=segment.signed_change,
        local_contribution_pct=segment.contribution_to_net_change_pct,
        global_contribution_pct=target.global_contribution_pct,
        evidence_strength=target.evidence_strength,
        evidence_refs=(reference,),
        prioritization_rationale=_prioritization_rationale(state, target),
    )
    decomposition = RCATargetDecompositionV1(
        source_scope=source_scope,
        dimension=test.dimension,
        parent_movement=parent_movement,
        dimension_net_movement=test.net_dimension_change,
        leading_segment_movement=segment.signed_change,
        remaining_segment_movement=parent_movement - segment.signed_change,
        downward_pressure=test.negative_pressure,
        positive_offsets=test.positive_offset,
        reconciliation_residual=parent_movement - test.net_dimension_change,
        reconciles=test.reconciles_to_kpi_change,
        evidence_refs=(reference,),
    )
    return tuple(steps), leading, decomposition


_QUALITY_CODE_BY_NAME = {
    "Required fields": "required_fields_missing",
    "Valid dates": "invalid_dates",
    "Requested periods present": "requested_period_missing",
    "Scoped requested periods present": "requested_period_missing",
    "Comparison row coverage": "comparison_coverage_incomplete",
    "Scoped comparison row coverage": "comparison_coverage_incomplete",
    "Comparison metric completeness": "metric_completeness_failed",
    "Scoped comparison metric completeness": "metric_completeness_failed",
}


def _quality_projection(
    state: InvestigationState,
    conclusion: InvestigationConclusion,
    evidence: _EvidenceBuilder,
) -> RCADataQualityV1:
    nodes = {item.node_id: item for item in state.investigation_path}
    target_id = conclusion.target_scope.target_path_node_id
    path_ids = set(conclusion.conclusion_path_node_ids)
    issues: list[RCADataQualityIssueV1] = []
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()

    sources: list[tuple[tuple[InvestigationFilter, ...], tuple[InvestigationHealthCheck, ...], bool]] = []
    if state.data_health:
        affects = target_id is None or "IN0" in path_ids
        sources.append(((), state.data_health, affects))
    for node in sorted(state.investigation_path, key=lambda item: item.depth):
        if not node.data_health:
            continue
        # Health attached to the selected target node describes attempted deeper work.
        affects = node.node_id in path_ids and node.node_id != target_id
        sources.append((node.filter_path, node.data_health, affects))

    for scope, checks, affects in sources:
        scope_key = tuple((item.dimension, item.segment) for item in scope)
        for check in checks:
            if check.status == "pass":
                continue
            identity = (check.evidence_id, scope_key)
            if identity in seen:
                continue
            seen.add(identity)
            code = _QUALITY_CODE_BY_NAME.get(check.name, "other_bounded_quality_issue")
            reference = evidence.add(
                f"quality:{check.evidence_id}:{scope_key}",
                kind="data_quality",
                source_scope=_public_scope(scope),
                target_scope=_public_scope(scope),
                quality_code=code,
            )
            evidence.refs.setdefault(check.evidence_id, reference)
            issues.append(
                RCADataQualityIssueV1(
                    code=code,
                    severity="blocking" if check.blocking and check.status == "fail" else "caution",
                    source_scope=_public_scope(scope),
                    affects_selected_target=affects,
                    evidence_refs=(reference,),
                )
            )

    for stop in conclusion.low_level_stops:
        if stop.stopping_reason != "insufficient_rows":
            continue
        scope_key = tuple((item.dimension, item.segment) for item in stop.filter_path)
        reference = evidence.add(
            f"quality-stop:{stop.scope_node_id}:{scope_key}",
            kind="data_quality",
            source_scope=_public_scope(stop.filter_path),
            target_scope=_public_scope(stop.filter_path),
            quality_code="insufficient_scope_rows",
        )
        issues.append(
            RCADataQualityIssueV1(
                code="insufficient_scope_rows",
                severity="blocking",
                source_scope=_public_scope(stop.filter_path),
                affects_selected_target=stop.scope_node_id != target_id,
                evidence_refs=(reference,),
            )
        )

    selected_block = any(
        item.severity == "blocking" and item.affects_selected_target for item in issues
    )
    status = "blocked" if selected_block else "caution" if issues else "pass"
    return RCADataQualityV1(status=status, issues=tuple(issues))


_CLAIM_MAP = {
    "mathematical_observation": "mathematical_observation",
    "leading_tested_contributor": "leading_tested_contributor",
    "robust_descriptive_explanation": "robust_descriptive_explanation",
    "competing_explanations": "competing_explanations",
    "data_quality_abstention": "data_quality_abstention",
    "inconclusive": "inconclusive",
}
_READINESS_MAP = {
    "not_ready_data_quality": "data_quality",
    "not_ready_incomplete_testing": "incomplete_testing",
    "not_ready_reconciliation": "reconciliation",
    "not_ready_competing_explanations": "competing_explanations",
    "not_ready_insufficient_evidence": "insufficient_evidence",
    "not_ready_verification_incomplete": "verification_incomplete",
}
_TERMINAL_MAP = {
    "completed": "completed",
    "completed_with_caveats": "completed_with_caveats",
    "inconclusive": "inconclusive",
    "blocked_by_data_quality": "blocked_by_data_quality",
    "blocked_by_reconciliation": "blocked_by_reconciliation",
    "bounded_by_max_depth": "bounded_by_max_depth",
    "no_material_driver": "no_material_driver",
    "incomplete_testing": "incomplete_testing",
}
_ROBUSTNESS_MAP = {
    "robust_no_material_challenge": "robust",
    "robust_with_caveats": "robust_with_caveats",
    "weakened": "weakened",
    "competing_explanations": "competing",
    "not_run": "not_verified",
    "abstain": "abstained",
}


def _conclusion_projection(
    conclusion: InvestigationConclusion, evidence: _EvidenceBuilder
) -> RCAConclusionV1:
    if conclusion.readiness_status == "ready":
        readiness = RCAExplanatoryReadinessV1(status="ready")
    elif conclusion.readiness_status == "ready_with_caveats":
        readiness = RCAExplanatoryReadinessV1(status="ready_with_caveats")
    else:
        readiness = RCAExplanatoryReadinessV1(
            status="not_ready", reason=_READINESS_MAP[conclusion.readiness_status]
        )

    applies = conclusion.readiness_checks.verification_applies_to_target
    if conclusion.claim_type == "data_quality_abstention":
        robustness_status = "abstained"
    elif not applies:
        robustness_status = "not_verified"
    else:
        robustness_status = _ROBUSTNESS_MAP[conclusion.robustness_status]

    references = tuple(
        evidence.refs[item]
        for item in conclusion.supporting_evidence_ids
        if item in evidence.refs
    )
    return RCAConclusionV1(
        claim=_CLAIM_MAP[conclusion.claim_type],
        readiness=readiness,
        robustness=RCARobustnessV1(
            status=robustness_status,
            applies_to_selected_target=applies,
        ),
        terminal_status=_TERMINAL_MAP[conclusion.terminal_category],
        caveats=conclusion.caveat_codes,
        recommended_next_action=conclusion.recommended_next_action,
        evidence_refs=references,
    )


def map_investigation_response(
    state: InvestigationState,
) -> RCAInvestigationResponseV1:
    """Purely project completed state into the safe public V1 response."""
    conclusion = state.final_conclusion
    if conclusion is None:
        raise RCAAPIServiceError(
            status_code=500,
            code="investigation_failed",
            message="The completed investigation has no publishable conclusion.",
        )
    evidence = _EvidenceBuilder.create()
    incident = next((item for item in state.evidence if item.kind == "incident"), None)
    incident_refs: tuple[str, ...] = ()
    if incident is not None:
        incident_ref = evidence.add(
            incident.evidence_id,
            kind="kpi_movement",
            baseline_value=state.baseline_value,
            comparison_value=state.comparison_value,
            signed_change=state.net_kpi_movement,
        )
        incident_refs = (incident_ref,)

    path, leader, decomposition = _path_projection(state, conclusion, evidence)
    quality = _quality_projection(state, conclusion, evidence)
    public_conclusion = _conclusion_projection(conclusion, evidence)

    response = RCAInvestigationResponseV1(
        investigation_id=UUID(state.investigation_id),
        kpi_movement=RCAKPIMovementV1(
            name=state.kpi.metric_name,
            unit=state.kpi.unit,
            baseline_period=state.baseline_period,
            comparison_period=state.comparison_period,
            baseline_value=state.baseline_value,
            comparison_value=state.comparison_value,
            signed_change=state.net_kpi_movement,
            evidence_refs=incident_refs,
        ),
        investigation_path=path,
        leading_contributor=leader,
        selected_decomposition=decomposition,
        conclusion=public_conclusion,
        data_quality=quality,
        supporting_evidence=tuple(evidence.items),
    )
    known = {item.evidence_ref for item in response.supporting_evidence}
    referenced = set(response.kpi_movement.evidence_refs)
    referenced.update(response.conclusion.evidence_refs)
    for step in response.investigation_path:
        referenced.update(step.evidence_refs)
    if response.leading_contributor:
        referenced.update(response.leading_contributor.evidence_refs)
    if response.selected_decomposition:
        referenced.update(response.selected_decomposition.evidence_refs)
    for issue in response.data_quality.issues:
        referenced.update(issue.evidence_refs)
    if not referenced.issubset(known):
        raise RCAAPIServiceError(
            status_code=500,
            code="investigation_failed",
            message="The completed investigation evidence could not be mapped safely.",
        )
    return response


def execute_rca_request(
    frame: pd.DataFrame, request: RCAInvestigationRequestV1
) -> RCAInvestigationResponseV1:
    validate_analysis_columns(frame, request)
    investigation_id = uuid4()
    internal_request = build_internal_request(request, investigation_id)
    state = run_single_level_investigation(frame, internal_request)
    return map_investigation_response(state)
