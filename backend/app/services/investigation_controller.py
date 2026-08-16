"""Bounded next-test controller for sequential deterministic RCA."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable

from pydantic import ValidationError

from app.domain.root_cause_contracts import (
    ControllerRejectionReason,
    HypothesisPlanningRecord,
    InvestigationFilter,
    NextTestActionProposal,
    SingleLevelInvestigationRequest,
)
from app.services.llm import generate_structured

logger = logging.getLogger(__name__)

_NUMERIC_CLAIM = re.compile(r"(?:\d|[%€$£¥])")
_CAUSAL_OR_CERTAINTY = re.compile(
    r"\b(cause[ds]?|causal|prove[ds]?|confirm(?:ed|s)?|certain(?:ly)?)\b", re.IGNORECASE
)
_UNSAFE_REASON = re.compile(
    r"\b(select|insert|update|delete|drop|python|sql|```|<script)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class ControllerDecision:
    proposal: NextTestActionProposal | None
    executed_action: str
    executed_dimension: str | None
    decision_source: str
    validation_status: str
    rejection_reason: ControllerRejectionReason | None
    fallback_used: bool


def _scope_label(path: tuple[InvestigationFilter, ...]) -> str:
    return " > ".join(f"{item.dimension}={item.segment}" for item in path) or "global"


def controller_prompt(
    request: SingleLevelInvestigationRequest,
    *,
    filter_path: tuple[InvestigationFilter, ...],
    available_dimensions: tuple[str, ...],
    tested_dimensions: tuple[str, ...],
    planning_record: HypothesisPlanningRecord,
    verified_results: tuple[dict[str, object], ...],
    remaining_iteration_budget: int,
) -> str:
    priorities = [
        {"dimension": item.target_dimension, "priority": item.priority, "status": item.status}
        for item in planning_record.validated_proposals
    ]
    return (
        "Choose exactly one bounded next action for a deterministic KPI investigation. "
        "Allowed actions are test_dimension or stop. A stop is only a request; deterministic sufficiency decides whether it is accepted. "
        "Do not calculate, invent findings, claim causality, change the KPI, write SQL/Python, or include numeric claims in brief_reason. "
        "Return only the strict JSON contract.\n"
        f"Goal: {request.goal}\n"
        f"KPI: {request.kpi.metric_name}; aggregation={request.kpi.aggregation}; time_grain={request.kpi.time_grain}; unit={request.kpi.unit or 'unspecified'}\n"
        f"Periods: baseline={request.baseline_period}; comparison={request.comparison_period}\n"
        f"Depth: {len(filter_path)}; scope: {_scope_label(filter_path)}\n"
        f"Available untested dimensions: {json.dumps(available_dimensions)}\n"
        f"Already tested in this exact scope: {json.dumps(tested_dimensions)}\n"
        f"Milestone 3 planning priorities: {json.dumps(priorities)}\n"
        f"Verified deterministic results: {json.dumps(verified_results)}\n"
        f"Remaining successful-test budget: {remaining_iteration_budget}\n"
        "Allowed reason_code values: highest_planner_priority, resolve_remaining_uncertainty, follow_supported_scope, compare_eligible_dimensions, no_useful_test_remaining."
    )


def _fallback_dimension(
    available_dimensions: tuple[str, ...], planning_record: HypothesisPlanningRecord
) -> str | None:
    available = set(available_dimensions)
    for proposal in sorted(planning_record.validated_proposals, key=lambda item: item.priority):
        if proposal.target_dimension in available:
            return proposal.target_dimension
    return available_dimensions[0] if available_dimensions else None


def choose_next_action(
    request: SingleLevelInvestigationRequest,
    *,
    filter_path: tuple[InvestigationFilter, ...],
    available_dimensions: tuple[str, ...],
    tested_dimensions: tuple[str, ...],
    planning_record: HypothesisPlanningRecord,
    verified_results: tuple[dict[str, object], ...],
    remaining_iteration_budget: int,
    data_health_blocked: bool = False,
    generator: Callable[[str, type[NextTestActionProposal]], NextTestActionProposal] | None = None,
) -> ControllerDecision:
    """Validate one controller proposal and resolve invalid actions to one fallback."""
    proposal: NextTestActionProposal | None = None
    rejection: ControllerRejectionReason | None = None
    try:
        generator = generator or generate_structured
        proposal = generator(
            controller_prompt(
                request,
                filter_path=filter_path,
                available_dimensions=available_dimensions,
                tested_dimensions=tested_dimensions,
                planning_record=planning_record,
                verified_results=verified_results,
                remaining_iteration_budget=remaining_iteration_budget,
            ),
            NextTestActionProposal,
        )
        if not isinstance(proposal, NextTestActionProposal):
            proposal = NextTestActionProposal.model_validate(proposal)
    except ValidationError:
        proposal = None
        rejection = "malformed_output"
    except Exception:
        proposal = None
        rejection = "provider_failure"
        logger.warning(
            "Controller decision fell back to deterministic mode investigation_id=%s decision_source=%s rejection=%s",
            request.investigation_id,
            "deterministic_fallback",
            rejection,
            extra={
                "investigation_id": request.investigation_id,
                "decision_source": "deterministic_fallback",
                "rejection": rejection,
            },
        )

    if rejection is None and data_health_blocked:
        rejection = "data_health_blocked"
    if rejection is None and proposal is not None:
        reason = proposal.brief_reason or ""
        if _NUMERIC_CLAIM.search(reason):
            rejection = "unsupported_numeric_claim"
        elif _CAUSAL_OR_CERTAINTY.search(reason):
            rejection = "causal_or_certainty_claim"
        elif _UNSAFE_REASON.search(reason):
            rejection = "unsafe_brief_reason"
        elif proposal.action == "stop" and available_dimensions:
            rejection = "premature_stop"
        elif proposal.action == "test_dimension":
            dimension = str(proposal.target_dimension)
            if dimension in {item.dimension for item in filter_path}:
                rejection = "dimension_in_filter_path"
            elif dimension in tested_dimensions:
                rejection = "dimension_already_tested_in_scope"
            elif dimension not in available_dimensions:
                rejection = "dimension_not_allowed"

    if rejection is None and proposal is not None:
        return ControllerDecision(
            proposal=proposal,
            executed_action=proposal.action,
            executed_dimension=proposal.target_dimension,
            decision_source="llm",
            validation_status="accepted",
            rejection_reason=None,
            fallback_used=False,
        )

    fallback = None if data_health_blocked else _fallback_dimension(available_dimensions, planning_record)
    return ControllerDecision(
        proposal=proposal,
        executed_action="test_dimension" if fallback is not None else "stop",
        executed_dimension=fallback,
        decision_source="deterministic_fallback",
        validation_status="rejected",
        rejection_reason=rejection,
        fallback_used=fallback is not None,
    )
