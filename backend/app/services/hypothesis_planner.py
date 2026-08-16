"""Bounded LLM dimension-prioritization for deterministic RCA.

The model may order approved dimensions only. It never receives raw rows and
never produces findings, calculations, SQL, or causal assertions.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable

from app.domain.root_cause_contracts import (
    HypothesisPlanningRecord,
    HypothesisProposal,
    HypothesisProposalSet,
    InvestigationFilter,
    PlannedHypothesis,
    RejectedHypothesisProposal,
    SingleLevelInvestigationRequest,
)
from app.services.llm import generate_structured

logger = logging.getLogger(__name__)

_NUMERIC_CLAIM = re.compile(r"(?:\d|[%€$£¥])")
_CAUSAL_OR_CERTAINTY = re.compile(r"\b(cause[ds]?|causal|prove[ds]?|confirm(?:ed|s)?|certain(?:ly)?)\b", re.IGNORECASE)
_UNSAFE_REASON = re.compile(r"\b(select|insert|update|delete|drop|python|sql|```|<script)\b", re.IGNORECASE)


def _scope_label(path: Iterable[InvestigationFilter]) -> str:
    values = tuple(path)
    return " > ".join(f"{item.dimension}={item.segment}" for item in values) or "global"


def planning_prompt(
    request: SingleLevelInvestigationRequest,
    *,
    schema: tuple[tuple[str, str], ...],
    filter_path: tuple[InvestigationFilter, ...],
    allowed_dimensions: tuple[str, ...],
    already_tested_dimensions: tuple[str, ...],
) -> str:
    return (
        "You prioritize which approved dimension should be tested first in a deterministic KPI investigation. "
        "Return JSON only. You may propose only target_dimension, reason_code, and optional brief_reason. "
        "Do not state findings, numbers, percentages, correlations, causal claims, columns, metric definitions, SQL, code, or business facts. "
        "Your proposal is untested planning information, never evidence.\n"
        f"Business question: {request.goal}\n"
        f"KPI: {request.kpi.metric_name}; aggregation={request.kpi.aggregation}; time_grain={request.kpi.time_grain}; unit={request.kpi.unit or 'unspecified'}\n"
        f"Periods: baseline={request.baseline_period}; comparison={request.comparison_period}\n"
        f"Schema (name, dtype): {list(schema)}\n"
        f"Current scope: {_scope_label(filter_path)}\n"
        f"Allowed dimensions, in safe fallback order: {list(allowed_dimensions)}\n"
        f"Already tested in this exact scope: {list(already_tested_dimensions)}\n"
        "Allowed reason_code values: kpi_relevance, business_structure, current_scope_relevance, unresolved_uncertainty, potential_explanatory_value."
    )


def _rejection_reason(proposal: HypothesisProposal, *, allowed: set[str], tested: set[str], seen: set[str]) -> str | None:
    target = proposal.target_dimension
    if target in tested:
        return "dimension_already_tested_in_scope"
    if target not in allowed:
        return "dimension_not_allowed"
    if target in seen:
        return "duplicate_dimension"
    reason = proposal.brief_reason or ""
    if _NUMERIC_CLAIM.search(reason):
        return "unsupported_numeric_claim"
    if _CAUSAL_OR_CERTAINTY.search(reason):
        return "causal_or_certainty_claim"
    if _UNSAFE_REASON.search(reason):
        return "unsafe_brief_reason"
    return None


def _statement(target_dimension: str) -> str:
    return f"{target_dimension} may contain a segment materially contributing to the KPI movement."


def plan_hypotheses(
    request: SingleLevelInvestigationRequest,
    *,
    schema: tuple[tuple[str, str], ...],
    filter_path: tuple[InvestigationFilter, ...] = (),
    allowed_dimensions: tuple[str, ...],
    already_tested_dimensions: tuple[str, ...] = (),
    planning_id: int,
    generator: Callable[[str, type[HypothesisProposalSet]], HypothesisProposalSet] | None = None,
) -> HypothesisPlanningRecord:
    """Return a complete safe ordering even if model output is partly invalid."""
    allowed = tuple(dimension for dimension in allowed_dimensions if dimension not in already_tested_dimensions)
    tested = set(already_tested_dimensions)
    rejected: list[RejectedHypothesisProposal] = []
    valid: list[HypothesisProposal] = []
    fallback_reason: str | None = None
    planner_mode = "llm"
    try:
        generator = generator or generate_structured
        output = generator(planning_prompt(request, schema=schema, filter_path=filter_path, allowed_dimensions=allowed, already_tested_dimensions=already_tested_dimensions), HypothesisProposalSet)
        seen: set[str] = set()
        for proposal in output.proposals:
            reason = _rejection_reason(proposal, allowed=set(allowed), tested=tested, seen=seen)
            if reason:
                rejected.append(RejectedHypothesisProposal(target_dimension=proposal.target_dimension, rejection_reason=reason))
                continue
            valid.append(proposal)
            seen.add(proposal.target_dimension)
        if not valid:
            fallback_reason = "no_valid_proposals"
            planner_mode = "deterministic_fallback"
    except Exception:
        valid = []
        fallback_reason = "provider_failure"
        planner_mode = "deterministic_fallback"
        logger.warning(
            "Hypothesis planning fell back to deterministic mode investigation_id=%s planner_mode=%s fallback_reason=%s",
            request.investigation_id,
            planner_mode,
            fallback_reason,
            extra={
                "investigation_id": request.investigation_id,
                "planner_mode": planner_mode,
                "fallback_reason": fallback_reason,
            },
        )

    planned: list[PlannedHypothesis] = []
    included = {item.target_dimension for item in valid}
    for proposal in valid:
        planned.append(PlannedHypothesis(hypothesis_id=f"HP{len(planned) + 1}", target_dimension=proposal.target_dimension, priority=len(planned) + 1, statement=_statement(proposal.target_dimension), reason_code=proposal.reason_code, brief_reason=proposal.brief_reason, source="llm"))
    for dimension in allowed:
        if dimension not in included:
            planned.append(PlannedHypothesis(hypothesis_id=f"HP{len(planned) + 1}", target_dimension=dimension, priority=len(planned) + 1, statement=_statement(dimension), reason_code="potential_explanatory_value", source="deterministic_fallback"))
    if valid and len(planned) > len(valid):
        planner_mode = "llm_with_fallback"
    if not planned:
        # No dimensions remain in this scope; this is not a provider failure.
        fallback_reason = fallback_reason or "no_valid_proposals"
        planner_mode = "deterministic_fallback"
    return HypothesisPlanningRecord(planning_id=f"IP{planning_id}", filter_path=filter_path, allowed_dimensions=allowed, validated_proposals=tuple(planned), rejected_proposals=tuple(rejected), fallback_reason=fallback_reason, planner_mode=planner_mode)


def update_hypothesis_statuses(
    record: HypothesisPlanningRecord, tests: Iterable[object], *, material_contribution_pct: float = 20.0
) -> HypothesisPlanningRecord:
    """Update proposal status only from deterministic dimension-test evidence."""
    by_dimension = {getattr(test, "dimension"): test for test in tests}
    updated: list[PlannedHypothesis] = []
    for proposal in record.validated_proposals:
        test = by_dimension.get(proposal.target_dimension)
        if test is None:
            updated.append(proposal)
            continue
        contributors = [item for item in test.segment_contributions if item.direction == "with_incident"]
        if not contributors:
            status = "rejected"
        else:
            share = max(abs(item.contribution_to_net_change_pct or 0) for item in contributors)
            status = "supported" if share >= material_contribution_pct else "weak" if share >= 5 else "rejected"
        updated.append(proposal.model_copy(update={"status": status, "evidence_ids": (test.evidence_id,)}))
    return record.model_copy(update={"validated_proposals": tuple(updated)})
