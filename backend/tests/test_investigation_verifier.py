import logging
from unittest.mock import patch

import pandas as pd
import pytest
from pydantic import ValidationError

from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.domain.root_cause_contracts import (
    ChallengeProposalSet,
    InvestigationState,
    SingleLevelInvestigationRequest,
)
from app.evals.investigation_verification_runner import (
    _challenge_planner,
    _controller,
    _hypothesis_planner,
    _request,
    _robust_rows,
    run_benchmark,
)
from app.services.investigation_verifier import (
    _build_target,
    challenge_planning_prompt,
    classify_competing_driver_ratio,
    classify_leading_segment_remainder_ratio,
    classify_offset_ratio,
    plan_challenges,
    verify_investigation,
)


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.599999, ("supports_leading", "none", "no_material_competitor_detected")),
        (0.60, ("inconclusive", "caution", "competing_driver_caution")),
        (0.799999, ("inconclusive", "caution", "competing_driver_caution")),
        (0.80, ("contradicts_leading", "material", "material_competing_driver")),
    ],
)
def test_competing_driver_policy_boundaries(ratio, expected):
    assert classify_competing_driver_ratio(ratio) == expected


@pytest.mark.parametrize(
    ("ratio", "expected_code"),
    [
        (0.20, "leading_segment_remainder_low"),
        (0.200001, "leading_segment_remainder_caution"),
        (0.499999, "leading_segment_remainder_caution"),
        (0.50, "leading_segment_remainder_material"),
    ],
)
def test_leading_segment_remainder_policy_boundaries(ratio, expected_code):
    assert classify_leading_segment_remainder_ratio(ratio)[2] == expected_code


@pytest.mark.parametrize(
    ("ratio", "expected_code"),
    [
        (0.099999, "offsets_low"),
        (0.10, "offsets_caution"),
        (0.199999, "offsets_caution"),
        (0.20, "offsets_material"),
    ],
)
def test_offset_policy_boundaries(ratio, expected_code):
    assert classify_offset_ratio(ratio)[2] == expected_code


def test_self_falsification_requires_evidence_driven_controller():
    with pytest.raises(ValidationError, match="evidence-driven controller"):
        SingleLevelInvestigationRequest.model_validate(
            {
                "investigation_id": "invalid",
                "goal": "Investigate revenue",
                "kpi": {
                    "metric_name": "Revenue",
                    "metric_column": "revenue",
                    "time_column": "date",
                },
                "baseline_period": "2026-01",
                "comparison_period": "2026-02",
                "candidate_dimensions": ["country"],
                "self_falsification_enabled": True,
            }
        )


def _provisional_state(tmp_path):
    path = tmp_path / "robust.csv"
    pd.DataFrame(_robust_rows()).to_csv(path, index=False)
    case = {"id": "unit", "maximum_depth": 1}
    request = _request(case)
    request["self_falsification_enabled"] = False
    with (
        patch("app.services.hypothesis_planner.generate_structured", _hypothesis_planner),
        patch("app.services.investigation_controller.generate_structured", _controller),
    ):
        raw = RootCauseAgent().execute(
            {"cleaned_path": str(path), "investigation_request": request}
        )["investigation_state"]
    return InvestigationState.model_validate(raw), SingleLevelInvestigationRequest.model_validate(
        {**request, "self_falsification_enabled": True}
    )


def test_llm_context_excludes_policy_thresholds_and_controls_order_only(tmp_path):
    state, request = _provisional_state(tmp_path)
    planning = plan_challenges(
        request, state, _build_target(state), generator=_challenge_planner("valid")
    )
    prompt = challenge_planning_prompt(
        request, state, planning.target, planning.applicable_challenges
    )
    assert "ordering only" in prompt
    assert "0.60" not in prompt
    assert "0.80" not in prompt
    assert "threshold" in prompt


def test_omitted_and_duplicate_challenges_are_completed_once(tmp_path):
    state, request = _provisional_state(tmp_path)

    def duplicate(_, output_type):
        assert output_type is ChallengeProposalSet
        return output_type.model_validate(
            {
                "proposals": [
                    {"challenge_type": "competing_driver", "reason_code": "compare_tested_decompositions"},
                    {"challenge_type": "competing_driver", "reason_code": "compare_tested_decompositions"},
                ]
            }
        )

    result = verify_investigation(state, request, generator=duplicate)
    types = [item.challenge_type for item in result.verification_records]
    assert len(types) == len(set(types)) == 5
    assert result.challenge_planning_record.planner_mode == "llm_with_fallback"
    assert any(
        item.rejection_reason == "duplicate_challenge"
        for item in result.challenge_planning_record.rejected_proposals
    )


def test_verification_records_classify_propositions_and_all_references_resolve(tmp_path):
    state, request = _provisional_state(tmp_path)
    result = verify_investigation(state, request, generator=_challenge_planner("valid"))
    known_tests = {item.test_id for item in result.tests_executed}
    known_evidence = {item.evidence_id for item in result.evidence}
    known_verifications = {item.verification_id for item in result.verification_records}
    assert all(set(item.source_test_ids).issubset(known_tests) for item in result.verification_records)
    assert all(set(item.source_evidence_ids).issubset(known_evidence) for item in result.verification_records)
    assert set((*result.supporting_verification_ids, *result.contradicting_verification_ids, *result.unresolved_verification_ids)) == known_verifications
    assert not hasattr(result, "supporting_evidence_ids")
    remainder = next(item for item in result.verification_records if item.challenge_type == "leading_segment_remainder")
    assert "does not measure global explanatory coverage" in remainder.rationale


def test_relevant_target_scope_blocking_quality_abstains_defensively(tmp_path):
    state, request = _provisional_state(tmp_path)
    root = state.investigation_path[0]
    failed = root.data_health[0].model_copy(update={"status": "fail", "blocking": True})
    unsafe_root = root.model_copy(update={"data_health": (failed, *root.data_health[1:])})
    unsafe = state.model_copy(update={"investigation_path": (unsafe_root, *state.investigation_path[1:])})
    result = verify_investigation(unsafe, request, generator=_challenge_planner("valid"))
    assert result.verification_status == "abstain"
    assert result.outcome == "data_quality_incident"
    assert result.leading_dimension == "country"
    assert result.leading_segment == "Germany"


def test_no_material_challenge_never_upgrades_weak_original_evidence(tmp_path):
    state, request = _provisional_state(tmp_path)
    weak = state.model_copy(update={"evidence_strength": "weak"})
    result = verify_investigation(weak, request, generator=_challenge_planner("valid"))
    assert result.verification_status == "robust_with_caveats"
    assert result.verification_evidence_strength == "weak"


def test_provider_failure_logs_warning_with_structured_fields(tmp_path, caplog):
    state, request = _provisional_state(tmp_path)

    def failing_generator(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    with caplog.at_level(logging.WARNING, logger="app.services.investigation_verifier"):
        planning = plan_challenges(
            request, state, _build_target(state), generator=failing_generator
        )

    assert planning.fallback_reason == "provider_failure"
    records = [item for item in caplog.records if item.name == "app.services.investigation_verifier"]
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].investigation_id == request.investigation_id
    assert records[0].fallback_reason == "provider_failure"
    assert records[0].rejection_reason == "provider_failure"


def test_milestone_5_production_path_benchmark():
    result = run_benchmark()
    assert result["release_ready"] is True, result
    assert result["passed"] == result["total"] == 7
    assert result["verification_metrics"]["paired_verification_reactivity_passed"] is True
    scope_case = next(item for item in result["results"] if item["id"] == "downstream_scope_quality_is_local")
    assert scope_case["leading_dimension"] == "country"
    assert scope_case["leading_segment"] == "Germany"
    assert scope_case["verification_status"] == "robust_no_material_challenge"
