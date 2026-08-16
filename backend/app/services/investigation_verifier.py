"""Bounded self-falsification for a provisional KPI explanation.

The model may order approved challenges only. Deterministic evidence selects
the target, performs every calculation, and assigns every robustness result.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable

from pydantic import ValidationError

from app.domain.root_cause_contracts import (
    ChallengePlanningRecord,
    ChallengeProposal,
    ChallengeProposalSet,
    ChallengeReasonCode,
    ChallengeType,
    DimensionContributionTest,
    InvestigationHealthCheck,
    InvestigationState,
    PlannedChallenge,
    RejectedChallengeProposal,
    SingleLevelInvestigationRequest,
    VerificationPolicyV1,
    VerificationRecord,
    VerificationTarget,
)
from app.services.llm import generate_structured

logger = logging.getLogger(__name__)

DEFAULT_VERIFICATION_POLICY = VerificationPolicyV1()
_CHALLENGE_ORDER: tuple[ChallengeType, ...] = (
    "data_quality",
    "competing_driver",
    "leading_segment_remainder",
    "offset_cancellation",
)
_REASON_BY_CHALLENGE: dict[ChallengeType, ChallengeReasonCode] = {
    "competing_driver": "compare_tested_decompositions",
    "leading_segment_remainder": "assess_leading_segment_coverage",
    "offset_cancellation": "assess_opposing_offsets",
    "data_quality": "assess_target_scope_health",
}
_NUMERIC_CLAIM = re.compile(r"(?:\d|[%€$£¥])")
_CAUSAL_OR_CERTAINTY = re.compile(
    r"\b(cause[ds]?|causal|prove[ds]?|confirm(?:ed|s)?|certain(?:ly)?|truth|true)\b",
    re.IGNORECASE,
)
_UNSAFE_REASON = re.compile(
    r"\b(select|insert|update|delete|drop|python|sql|```|<script)\b",
    re.IGNORECASE,
)


def _target_scope_node(state: InvestigationState, test_id: str):
    for node in sorted(state.investigation_path, key=lambda item: item.depth):
        if test_id in node.test_ids:
            return node
    return None


def _leading_test(state: InvestigationState) -> DimensionContributionTest | None:
    candidates = []
    for test in state.tests_executed:
        if test.dimension != state.leading_dimension:
            continue
        if any(
            item.segment == state.leading_segment and item.direction == "with_incident"
            for item in test.segment_contributions
        ):
            candidates.append(test)
    if not candidates:
        return None
    path_test_ids = {
        test_id for node in state.investigation_path for test_id in node.test_ids
    }
    candidates.sort(key=lambda item: (item.test_id not in path_test_ids, item.test_id))
    return candidates[0]


def _build_target(state: InvestigationState) -> VerificationTarget | None:
    if not state.leading_dimension or not state.leading_segment:
        return None
    test = _leading_test(state)
    if test is None:
        return None
    node = _target_scope_node(state, test.test_id)
    return VerificationTarget(
        scope_node_id=node.node_id if node else "IN0",
        filter_path=node.filter_path if node else (),
        target_dimension=state.leading_dimension,
        target_segment=state.leading_segment,
        source_test_ids=(test.test_id,),
        source_evidence_ids=(test.evidence_id,),
    )


def _scope_tests(
    state: InvestigationState, target: VerificationTarget
) -> tuple[DimensionContributionTest, ...]:
    node = next(
        (item for item in state.investigation_path if item.node_id == target.scope_node_id),
        None,
    )
    if node is None:
        return state.tests_executed
    allowed = set(node.test_ids)
    return tuple(test for test in state.tests_executed if test.test_id in allowed)


def _scope_health(
    state: InvestigationState, target: VerificationTarget
) -> tuple[InvestigationHealthCheck, ...]:
    node = next(
        (item for item in state.investigation_path if item.node_id == target.scope_node_id),
        None,
    )
    if node is not None:
        return node.data_health
    return state.data_health


def applicable_challenges(
    state: InvestigationState, target: VerificationTarget
) -> tuple[ChallengeType, ...]:
    tests = _scope_tests(state, target)
    leading = _leading_test(state)
    available: set[ChallengeType] = set()
    if _scope_health(state, target):
        available.add("data_quality")
    if leading is not None and any(
        test.dimension != target.target_dimension for test in tests
    ):
        available.add("competing_driver")
    if (
        state.net_kpi_movement is not None
        and state.leading_signed_contribution is not None
        and abs(state.net_kpi_movement) > 0
    ):
        available.add("leading_segment_remainder")
    if leading is not None:
        available.add("offset_cancellation")
    return tuple(item for item in _CHALLENGE_ORDER if item in available)


def challenge_planning_prompt(
    request: SingleLevelInvestigationRequest,
    state: InvestigationState,
    target: VerificationTarget,
    applicable: tuple[ChallengeType, ...],
) -> str:
    tested_dimensions = tuple(test.dimension for test in _scope_tests(state, target))
    return (
        "Order the approved deterministic challenges for one provisional descriptive KPI explanation. "
        "You control ordering only: deterministic applicability appends every omitted required check, "
        "and deterministic code assigns all results. Do not calculate, create evidence, modify thresholds, "
        "define a target, claim causality or truth, write SQL/Python, or include numeric claims in brief_reason. "
        "Return only the strict JSON contract.\n"
        f"Goal: {request.goal}\n"
        f"KPI: {request.kpi.metric_name}; aggregation={request.kpi.aggregation}; "
        f"time_grain={request.kpi.time_grain}; unit={request.kpi.unit or 'unspecified'}\n"
        f"Periods: baseline={request.baseline_period}; comparison={request.comparison_period}\n"
        f"Target: {json.dumps(target.model_dump(mode='json'))}\n"
        f"Existing evidence strength label: {state.evidence_strength}\n"
        f"Tested approved dimensions in the exact target scope: {json.dumps(tested_dimensions)}\n"
        f"Applicable mandatory challenge types: {json.dumps(applicable)}\n"
        "Allowed challenge/reason pairs: competing_driver/compare_tested_decompositions; "
        "leading_segment_remainder/assess_leading_segment_coverage; "
        "offset_cancellation/assess_opposing_offsets; data_quality/assess_target_scope_health."
    )


def _proposal_rejection(
    proposal: ChallengeProposal,
    *,
    applicable: set[ChallengeType],
    seen: set[ChallengeType],
) -> str | None:
    if proposal.challenge_type not in applicable:
        return "challenge_not_applicable"
    if proposal.challenge_type in seen:
        return "duplicate_challenge"
    if proposal.reason_code != _REASON_BY_CHALLENGE[proposal.challenge_type]:
        return "reason_code_mismatch"
    reason = proposal.brief_reason or ""
    if _NUMERIC_CLAIM.search(reason):
        return "unsupported_numeric_claim"
    if _CAUSAL_OR_CERTAINTY.search(reason):
        return "causal_or_certainty_claim"
    if _UNSAFE_REASON.search(reason):
        return "unsafe_brief_reason"
    return None


def plan_challenges(
    request: SingleLevelInvestigationRequest,
    state: InvestigationState,
    target: VerificationTarget,
    *,
    policy: VerificationPolicyV1 = DEFAULT_VERIFICATION_POLICY,
    generator: Callable[[str, type[ChallengeProposalSet]], ChallengeProposalSet]
    | None = None,
) -> ChallengePlanningRecord:
    applicable = applicable_challenges(state, target)
    accepted: list[ChallengeProposal] = []
    rejected: list[RejectedChallengeProposal] = []
    fallback_reason: str | None = None
    try:
        generator = generator or generate_structured
        output = generator(
            challenge_planning_prompt(request, state, target, applicable),
            ChallengeProposalSet,
        )
        if not isinstance(output, ChallengeProposalSet):
            output = ChallengeProposalSet.model_validate(output)
        seen: set[ChallengeType] = set()
        for proposal in output.proposals:
            rejection = _proposal_rejection(
                proposal, applicable=set(applicable), seen=seen
            )
            if rejection:
                rejected.append(
                    RejectedChallengeProposal(
                        challenge_type=proposal.challenge_type,
                        rejection_reason=rejection,
                    )
                )
                continue
            accepted.append(proposal)
            seen.add(proposal.challenge_type)
        if not accepted:
            fallback_reason = "no_valid_proposals"
    except ValidationError:
        fallback_reason = "malformed_output"
        rejected.append(
            RejectedChallengeProposal(
                challenge_type="<output>", rejection_reason="malformed_output"
            )
        )
    except Exception:
        fallback_reason = "provider_failure"
        rejected.append(
            RejectedChallengeProposal(
                challenge_type="<provider>", rejection_reason="provider_failure"
            )
        )
        for item in rejected:
            logger.warning(
                "Challenge planning fell back to deterministic mode investigation_id=%s fallback_reason=%s rejection_reason=%s",
                request.investigation_id,
                fallback_reason,
                item.rejection_reason,
                extra={
                    "investigation_id": request.investigation_id,
                    "fallback_reason": fallback_reason,
                    "rejection_reason": item.rejection_reason,
                },
            )

    planned: list[PlannedChallenge] = []
    included: set[ChallengeType] = set()
    for proposal in accepted:
        planned.append(
            PlannedChallenge(
                challenge_id=f"VC{len(planned) + 1}",
                challenge_type=proposal.challenge_type,
                reason_code=proposal.reason_code,
                brief_reason=proposal.brief_reason,
                source="llm",
            )
        )
        included.add(proposal.challenge_type)
    omitted = tuple(item for item in applicable if item not in included)
    for challenge_type in omitted:
        planned.append(
            PlannedChallenge(
                challenge_id=f"VC{len(planned) + 1}",
                challenge_type=challenge_type,
                reason_code=_REASON_BY_CHALLENGE[challenge_type],
                source="deterministic_fallback",
            )
        )
    if omitted and fallback_reason is None:
        fallback_reason = "omitted_required_challenges"
    if accepted and omitted:
        planner_mode = "llm_with_fallback"
    elif accepted:
        planner_mode = "llm"
    else:
        planner_mode = "deterministic_fallback"
    return ChallengePlanningRecord(
        planning_id="VP1",
        verification_policy_version=policy.verification_policy_version,
        target=target,
        applicable_challenges=applicable,
        validated_challenges=tuple(planned),
        rejected_proposals=tuple(rejected),
        fallback_reason=fallback_reason,
        planner_mode=planner_mode,
    )


def classify_competing_driver_ratio(
    ratio: float, policy: VerificationPolicyV1 = DEFAULT_VERIFICATION_POLICY
) -> tuple[str, str, str]:
    if ratio >= policy.competing_driver_material_ratio:
        return "contradicts_leading", "material", "material_competing_driver"
    if ratio >= policy.competing_driver_caution_ratio:
        return "inconclusive", "caution", "competing_driver_caution"
    return "supports_leading", "none", "no_material_competitor_detected"


def classify_leading_segment_remainder_ratio(
    ratio: float, policy: VerificationPolicyV1 = DEFAULT_VERIFICATION_POLICY
) -> tuple[str, str, str]:
    if ratio >= policy.leading_segment_remainder_material_ratio:
        return (
            "contradicts_leading",
            "material",
            "leading_segment_remainder_material",
        )
    if ratio > policy.leading_segment_remainder_caution_ratio:
        return (
            "inconclusive",
            "caution",
            "leading_segment_remainder_caution",
        )
    return "supports_leading", "none", "leading_segment_remainder_low"


def classify_offset_ratio(
    ratio: float, policy: VerificationPolicyV1 = DEFAULT_VERIFICATION_POLICY
) -> tuple[str, str, str]:
    if ratio >= policy.offset_material_ratio:
        return "contradicts_leading", "material", "offsets_material"
    if ratio >= policy.offset_caution_ratio:
        return "inconclusive", "caution", "offsets_caution"
    return "supports_leading", "none", "offsets_low"


def _competing_driver_record(
    state: InvestigationState,
    target: VerificationTarget,
    verification_id: str,
    policy: VerificationPolicyV1,
) -> VerificationRecord:
    leading_test = _leading_test(state)
    assert leading_test is not None and state.leading_signed_contribution is not None
    alternatives = []
    for test in _scope_tests(state, target):
        if test.dimension == target.target_dimension:
            continue
        aligned = [
            item for item in test.segment_contributions if item.direction == "with_incident"
        ]
        if aligned:
            aligned.sort(key=lambda item: (-abs(item.signed_change), item.segment))
            alternatives.append((aligned[0], test))
    alternatives.sort(
        key=lambda item: (-abs(item[0].signed_change), item[0].dimension, item[0].segment)
    )
    runner, runner_test = alternatives[0] if alternatives else (None, None)
    ratio = (
        abs(runner.signed_change) / abs(state.leading_signed_contribution)
        if runner is not None and abs(state.leading_signed_contribution) > 0
        else 0.0
    )
    result, materiality, code = classify_competing_driver_ratio(ratio, policy)
    source_tests = (leading_test.test_id,) + (
        (runner_test.test_id,) if runner_test is not None else ()
    )
    source_evidence = (leading_test.evidence_id,) + (
        (runner_test.evidence_id,) if runner_test is not None else ()
    )
    if runner is None:
        rationale = (
            "No material competing contributor was detected among the tested approved "
            "dimensions in the exact target scope."
        )
    else:
        rationale = (
            f"{runner.dimension}={runner.segment} is the strongest alternative tested "
            f"decomposition at {ratio:.3f} of the provisional leader's magnitude."
        )
    return VerificationRecord(
        verification_id=verification_id,
        verification_policy_version=policy.verification_policy_version,
        challenge_type="competing_driver",
        target=target,
        source_test_ids=source_tests,
        source_evidence_ids=source_evidence,
        result=result,
        materiality=materiality,
        result_code=code,
        metrics={
            "runner_up_ratio": ratio,
            "runner_up_dimension": runner.dimension if runner else None,
            "runner_up_segment": runner.segment if runner else None,
        },
        rationale=rationale,
    )


def _remainder_record(
    state: InvestigationState,
    target: VerificationTarget,
    verification_id: str,
    policy: VerificationPolicyV1,
) -> VerificationRecord:
    assert state.net_kpi_movement is not None
    assert state.leading_signed_contribution is not None
    remainder = state.net_kpi_movement - state.leading_signed_contribution
    ratio = abs(remainder) / abs(state.net_kpi_movement)
    result, materiality, code = classify_leading_segment_remainder_ratio(ratio, policy)
    incident_ids = tuple(
        item.evidence_id for item in state.evidence if item.kind == "incident"
    )
    return VerificationRecord(
        verification_id=verification_id,
        verification_policy_version=policy.verification_policy_version,
        challenge_type="leading_segment_remainder",
        target=target,
        source_test_ids=target.source_test_ids,
        source_evidence_ids=tuple(
            dict.fromkeys((*target.source_evidence_ids, *incident_ids))
        ),
        result=result,
        materiality=materiality,
        result_code=code,
        metrics={
            "leading_segment_remainder": remainder,
            "leading_segment_remainder_ratio": ratio,
        },
        rationale=(
            f"Movement remaining outside the leading segment within its decomposition "
            f"is {ratio:.3f} of net KPI movement. This remainder is scoped to that "
            "decomposition and does not measure global explanatory coverage."
        ),
    )


def _offset_record(
    state: InvestigationState,
    target: VerificationTarget,
    verification_id: str,
    policy: VerificationPolicyV1,
) -> VerificationRecord:
    leading_test = _leading_test(state)
    assert leading_test is not None and state.net_kpi_movement is not None
    opposing = sum(
        abs(item.signed_change)
        for item in leading_test.segment_contributions
        if item.direction == "positive_offset"
    )
    ratio = opposing / abs(state.net_kpi_movement)
    result, materiality, code = classify_offset_ratio(ratio, policy)
    return VerificationRecord(
        verification_id=verification_id,
        verification_policy_version=policy.verification_policy_version,
        challenge_type="offset_cancellation",
        target=target,
        source_test_ids=(leading_test.test_id,),
        source_evidence_ids=(leading_test.evidence_id,),
        result=result,
        materiality=materiality,
        result_code=code,
        metrics={"opposing_offset": opposing, "offset_to_net_movement_ratio": ratio},
        rationale=(
            f"Opposing signed movement inside the leading decomposition is {ratio:.3f} "
            "of net KPI movement; contributions above the net movement remain valid."
        ),
    )


def _data_quality_record(
    state: InvestigationState,
    target: VerificationTarget,
    verification_id: str,
    policy: VerificationPolicyV1,
) -> VerificationRecord:
    checks = _scope_health(state, target)
    blocking = [item for item in checks if item.status == "fail" and item.blocking]
    cautions = [item for item in checks if item.status == "caution" or (item.status == "fail" and not item.blocking)]
    if blocking:
        result, materiality, code = (
            "contradicts_leading",
            "blocking",
            "target_scope_quality_blocking",
        )
        rationale = "A blocking data-quality failure affects the exact scope that produced the provisional explanation."
    elif cautions:
        result, materiality, code = (
            "inconclusive",
            "caution",
            "target_scope_quality_caution",
        )
        rationale = "A non-blocking data-quality warning affects the exact target scope."
    else:
        result, materiality, code = (
            "supports_leading",
            "none",
            "target_scope_quality_safe",
        )
        rationale = "No material data-quality challenge was detected in the exact target scope."
    return VerificationRecord(
        verification_id=verification_id,
        verification_policy_version=policy.verification_policy_version,
        challenge_type="data_quality",
        target=target,
        source_test_ids=target.source_test_ids,
        source_evidence_ids=tuple(item.evidence_id for item in checks),
        result=result,
        materiality=materiality,
        result_code=code,
        metrics={
            "target_scope_health_check_count": len(checks),
            "target_scope_blocking_failure_count": len(blocking),
            "target_scope_caution_count": len(cautions),
        },
        rationale=rationale,
    )


def _downgrade_strength(strength: str) -> str:
    return {
        "strong": "moderate",
        "moderate": "weak",
        "weak": "weak",
        "insufficient": "insufficient",
    }[strength]


def _reassess(state: InvestigationState, records: tuple[VerificationRecord, ...]):
    if any(
        item.challenge_type == "data_quality" and item.materiality == "blocking"
        for item in records
    ):
        return (
            "abstain",
            "insufficient",
            "data_quality_incident",
            "The exact target scope has a blocking data-quality issue; the descriptive explanation is not safe to accept.",
        )
    if any(item.result_code == "material_competing_driver" for item in records):
        return (
            "competing_explanations",
            "insufficient",
            "inconclusive",
            "A near-equal contributor exists in another tested decomposition; the provisional leader is not uniquely explanatory.",
        )
    if any(
        item.result_code == "leading_segment_remainder_material" for item in records
    ):
        return (
            "weakened",
            "weak",
            "inconclusive",
            "The leading segment remains the mathematical leader, but it does not provide a sufficiently complete descriptive account by itself.",
        )
    caveat = any(item.materiality in {"caution", "material"} for item in records)
    if caveat or state.evidence_strength != "strong":
        return (
            "robust_with_caveats",
            _downgrade_strength(state.evidence_strength),
            state.outcome,
            "The provisional explanation survived bounded checks with material or evidence-strength caveats; no causal claim is established.",
        )
    return (
        "robust_no_material_challenge",
        state.evidence_strength,
        state.outcome,
        "No material challenge was detected among the bounded checks and tested approved dimensions; this does not establish causality or truth.",
    )


def verify_investigation(
    state: InvestigationState,
    request: SingleLevelInvestigationRequest,
    *,
    policy: VerificationPolicyV1 = DEFAULT_VERIFICATION_POLICY,
    generator: Callable[[str, type[ChallengeProposalSet]], ChallengeProposalSet]
    | None = None,
) -> InvestigationState:
    """Challenge one provisional leader once, then deterministically stop."""
    if state.outcome != "strongest_supported_driver":
        return state
    target = _build_target(state)
    if target is None:
        return state.model_copy(
            update={
                "outcome": "inconclusive",
                "verification_policy_version": policy.verification_policy_version,
                "verification_status": "abstain",
                "verification_evidence_strength": "insufficient",
                "verification_rationale": "The provisional explanation could not be resolved to an exact deterministic test and scope.",
            }
        )
    planning = plan_challenges(
        request, state, target, policy=policy, generator=generator
    )
    records: list[VerificationRecord] = []
    executed: set[ChallengeType] = set()
    for planned in planning.validated_challenges:
        if planned.challenge_type in executed:
            raise RuntimeError("Duplicate challenge execution was blocked")
        verification_id = f"IV{len(records) + 1}"
        if planned.challenge_type == "competing_driver":
            record = _competing_driver_record(
                state, target, verification_id, policy
            )
        elif planned.challenge_type == "leading_segment_remainder":
            record = _remainder_record(state, target, verification_id, policy)
        elif planned.challenge_type == "offset_cancellation":
            record = _offset_record(state, target, verification_id, policy)
        else:
            record = _data_quality_record(state, target, verification_id, policy)
        records.append(record)
        executed.add(planned.challenge_type)

    records_tuple = tuple(records)
    known_tests = {item.test_id for item in state.tests_executed}
    known_evidence = {item.evidence_id for item in state.evidence}
    for record in records_tuple:
        if not set(record.source_test_ids).issubset(known_tests):
            raise RuntimeError("Verification source test reference does not resolve")
        if not set(record.source_evidence_ids).issubset(known_evidence):
            raise RuntimeError("Verification source evidence reference does not resolve")
    supporting = tuple(
        item.verification_id
        for item in records_tuple
        if item.result == "supports_leading"
    )
    contradicting = tuple(
        item.verification_id
        for item in records_tuple
        if item.result == "contradicts_leading"
    )
    unresolved = tuple(
        item.verification_id
        for item in records_tuple
        if item.result == "inconclusive"
    )
    known_verifications = {item.verification_id for item in records_tuple}
    if set((*supporting, *contradicting, *unresolved)) != known_verifications:
        raise RuntimeError("Verification classification references are incomplete")
    status, strength, outcome, rationale = _reassess(state, records_tuple)
    return state.model_copy(
        update={
            "outcome": outcome,
            "verification_policy_version": policy.verification_policy_version,
            "challenge_planning_record": planning,
            "verification_records": records_tuple,
            "supporting_verification_ids": supporting,
            "contradicting_verification_ids": contradicting,
            "unresolved_verification_ids": unresolved,
            "verification_status": status,
            "verification_evidence_strength": strength,
            "verification_rationale": rationale,
        }
    )
