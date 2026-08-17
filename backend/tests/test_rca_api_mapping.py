from unittest.mock import patch
from uuid import uuid4

import pandas as pd
import pytest

from app.domain.root_cause_contracts import (
    AdditiveKPISemanticDefinition,
    HypothesisPlanningRecord,
    InvestigationPathNode,
    InvestigationState,
    PlannedHypothesis,
    SingleLevelInvestigationRequest,
)
from app.services.rca_api import (
    RCAAPIServiceError,
    _prioritization_rationale,
    load_governed_dataset,
    map_investigation_response,
)
from app.services.root_cause import run_single_level_investigation


def _request(**updates):
    payload = {
        "investigation_id": str(uuid4()),
        "goal": "Investigate revenue",
        "kpi": {
            "metric_name": "Revenue",
            "metric_column": "revenue",
            "time_column": "date",
            "aggregation": "sum",
            "time_grain": "month",
            "unit": "EUR",
        },
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "device", "customer_type"],
        "maximum_depth": 3,
        "minimum_rows_per_period_for_drill_down": 1,
        "conclusion_compilation_enabled": True,
    }
    payload.update(updates)
    return SingleLevelInvestigationRequest.model_validate(payload)


def _rows_from_changes(cells):
    rows = []
    for country, device, customer_type, change in cells:
        rows.extend(
            [
                {"date": "2026-01-01", "country": country, "device": device, "customer_type": customer_type, "revenue": 200.0},
                {"date": "2026-02-01", "country": country, "device": device, "customer_type": customer_type, "revenue": 200.0 + change},
            ]
        )
    return rows


def recursive_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Returning", -45),
            ("Germany", "Mobile", "New", -15),
            ("Germany", "Desktop", "Returning", -10),
            ("Germany", "Desktop", "New", -10),
            ("France", "Mobile", "Returning", -2),
            ("France", "Desktop", "New", -3),
            ("UK", "Mobile", "New", -5),
            ("UK", "Desktop", "Returning", -10),
        ]
    )


def _add_group(rows, period, country, device, customer_type, count, total):
    for _ in range(count):
        rows.append(
            {"date": f"{period}-01", "country": country, "device": device, "customer_type": customer_type, "revenue": total / count}
        )


def downstream_quality_rows():
    rows = []
    for args in (
        ("2026-01", "Germany", "Mobile", "Returning", 6, 120),
        ("2026-01", "Germany", "Mobile", "New", 4, 80),
        ("2026-01", "Germany", "Desktop", "Returning", 3, 60),
        ("2026-01", "Germany", "Desktop", "New", 2, 40),
        ("2026-02", "Germany", "Mobile", "Returning", 3, 60),
        ("2026-02", "Germany", "Mobile", "New", 2, 40),
        ("2026-02", "Germany", "Desktop", "Returning", 6, 54),
        ("2026-02", "Germany", "Desktop", "New", 4, 36),
        ("2026-01", "France", "Mobile", "Returning", 8, 160),
        ("2026-01", "France", "Desktop", "New", 7, 140),
        ("2026-02", "France", "Mobile", "Returning", 8, 155),
        ("2026-02", "France", "Desktop", "New", 7, 135),
    ):
        _add_group(rows, *args)
    return rows


def _response(rows, **request_updates):
    state = run_single_level_investigation(pd.DataFrame(rows), _request(**request_updates))
    return map_investigation_response(state)


def test_recursive_projection_has_exact_source_and_target_scopes():
    response = _response(recursive_rows())
    returning = response.investigation_path[-1]

    assert [(item.dimension, item.segment) for item in returning.source_scope] == [
        ("country", "Germany"),
        ("device", "Mobile"),
    ]
    assert [(item.dimension, item.segment) for item in returning.target_scope] == [
        ("country", "Germany"),
        ("device", "Mobile"),
        ("customer_type", "Returning"),
    ]
    assert response.leading_contributor.source_scope == returning.source_scope
    assert response.leading_contributor.target_scope == returning.target_scope


def test_selected_decomposition_arithmetic_is_exactly_scoped():
    response = _response(recursive_rows())
    decomposition = response.selected_decomposition

    assert decomposition.dimension == "customer_type"
    assert abs(decomposition.dimension_net_movement - decomposition.parent_movement) < 1e-9
    assert decomposition.remaining_segment_movement == (
        decomposition.parent_movement - decomposition.leading_segment_movement
    )
    assert decomposition.reconciliation_residual == (
        decomposition.parent_movement - decomposition.dimension_net_movement
    )
    assert decomposition.reconciles is True
    serialized = response.model_dump_json()
    assert "unexplained" not in serialized
    assert "outside_decomposition" not in serialized


def test_downstream_quality_block_does_not_block_selected_target():
    response = _response(downstream_quality_rows())

    assert response.leading_contributor.dimension == "device"
    assert response.leading_contributor.segment == "Mobile"
    assert response.conclusion.claim == "leading_tested_contributor"
    assert response.data_quality.status == "caution"
    downstream = [item for item in response.data_quality.issues if item.severity == "blocking"]
    assert downstream
    assert all(item.affects_selected_target is False for item in downstream)
    assert "downstream_scope_data_quality" in response.conclusion.caveats


def test_selected_target_quality_failure_is_blocking_abstention():
    unsafe = [item for item in recursive_rows() if item["date"] == "2026-01-01"]
    unsafe.append(next(item for item in recursive_rows() if item["date"] == "2026-02-01"))
    response = _response(unsafe, maximum_depth=1)

    assert response.conclusion.claim == "data_quality_abstention"
    assert response.data_quality.status == "blocked"
    assert any(item.affects_selected_target for item in response.data_quality.issues)


def test_every_public_evidence_reference_resolves_and_internal_ids_do_not_leak():
    response = _response(recursive_rows())
    payload = response.model_dump(mode="json")
    known = {item["evidence_ref"] for item in payload["supporting_evidence"]}
    references = set(payload["kpi_movement"]["evidence_refs"])
    for step in payload["investigation_path"]:
        references.update(step["evidence_refs"])
    references.update(payload["leading_contributor"]["evidence_refs"])
    references.update(payload["selected_decomposition"]["evidence_refs"])
    references.update(payload["conclusion"]["evidence_refs"])
    for issue in payload["data_quality"]["issues"]:
        references.update(issue["evidence_refs"])

    assert references <= known
    serialized = response.model_dump_json()
    for forbidden in ("test_id", "node_id", "verification_id", "planning", "iterations", "file_path", "values"):
        assert forbidden not in serialized


def test_governed_dataset_loader_rejects_outside_missing_and_unsupported_paths(tmp_path):
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("a\n1\n", encoding="utf-8")
    missing = tmp_path / "missing.csv"
    unsupported = tmp_path / "data.json"
    unsupported.write_text("{}", encoding="utf-8")

    for path in (outside, missing, unsupported):
        with pytest.raises(RCAAPIServiceError) as error:
            load_governed_dataset(type("Dataset", (), {"file_path": str(path)})(), tmp_path)
        assert error.value.code == "dataset_unavailable"


def _state(records):
    return InvestigationState(
        investigation_id=str(uuid4()),
        goal="Investigate revenue",
        kpi=AdditiveKPISemanticDefinition(metric_name="Revenue", metric_column="revenue", time_column="date"),
        baseline_period="2026-01",
        comparison_period="2026-02",
        candidate_dimensions=("country", "device"),
        outcome="strongest_supported_driver",
        stopping_reason="Controlled investigation completed.",
        hypothesis_planning_records=tuple(records),
    )


def _hp(hypothesis_id, target_dimension, priority, source, brief_reason=None):
    return PlannedHypothesis(
        hypothesis_id=hypothesis_id,
        target_dimension=target_dimension,
        priority=priority,
        statement=f"{target_dimension} may contain a material segment contributor.",
        reason_code="potential_explanatory_value",
        brief_reason=brief_reason,
        source=source,
    )


def test_prioritization_rationale_populated_when_llm_proposed_the_winning_dimension():
    record = HypothesisPlanningRecord(
        planning_id="IP1",
        allowed_dimensions=("country", "device"),
        validated_proposals=(_hp("HP1", "country", 1, "llm", "Country splits often shift after promo rollouts."),),
        planner_mode="llm",
    )
    state = _state([record])
    target = InvestigationPathNode(
        node_id="IN1", depth=1, parent_node_id="IN0", planning_id="IP1", selected_dimension="country"
    )

    assert _prioritization_rationale(state, target) == "Country splits often shift after promo rollouts."


def test_prioritization_rationale_null_when_winning_dimension_came_from_deterministic_fallback():
    record = HypothesisPlanningRecord(
        planning_id="IP1",
        allowed_dimensions=("country", "device"),
        validated_proposals=(_hp("HP1", "country", 1, "deterministic_fallback"),),
        planner_mode="deterministic_fallback",
        fallback_reason="provider_failure",
    )
    state = _state([record])
    target = InvestigationPathNode(
        node_id="IN1", depth=1, parent_node_id="IN0", planning_id="IP1", selected_dimension="country"
    )

    assert _prioritization_rationale(state, target) is None


def test_prioritization_rationale_null_when_llm_proposed_different_dimensions_than_the_winner():
    record = HypothesisPlanningRecord(
        planning_id="IP1",
        allowed_dimensions=("country", "device"),
        validated_proposals=(
            _hp("HP1", "device", 1, "llm", "Device mix looked uneven in the scope summary."),
            _hp("HP2", "country", 2, "deterministic_fallback"),
        ),
        planner_mode="llm_with_fallback",
    )
    state = _state([record])
    target = InvestigationPathNode(
        node_id="IN1", depth=1, parent_node_id="IN0", planning_id="IP1", selected_dimension="country"
    )

    assert _prioritization_rationale(state, target) is None


def _no_provider(*_args, **_kwargs):
    raise RuntimeError("no provider in test")


def _verified_request(candidate_dimensions, **updates):
    payload = {
        "investigation_id": str(uuid4()),
        "goal": "Investigate revenue",
        "kpi": {
            "metric_name": "Revenue",
            "metric_column": "revenue",
            "time_column": "date",
            "aggregation": "sum",
            "time_grain": "month",
            "unit": "EUR",
        },
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": candidate_dimensions,
        "maximum_depth": 1,
        "minimum_rows_per_period_for_drill_down": 1,
        "evidence_driven_control_enabled": True,
        "self_falsification_enabled": True,
        "conclusion_compilation_enabled": True,
        # Coverage checks are scope-wide and unrelated to what this challenge
        # tests; relaxed so they never pre-empt the segment-reliability checks.
        "comparison_coverage_ratio": 0.01,
    }
    payload.update(updates)
    return SingleLevelInvestigationRequest.model_validate(payload)


def _verified_response(rows, candidate_dimensions, **request_updates):
    request = _verified_request(candidate_dimensions, **request_updates)
    with (
        patch("app.services.hypothesis_planner.generate_structured", _no_provider),
        patch("app.services.investigation_controller.generate_structured", _no_provider),
        patch("app.services.investigation_verifier.generate_structured", _no_provider),
    ):
        state = run_single_level_investigation(pd.DataFrame(rows), request)
    return state, map_investigation_response(state)


def test_segment_reliability_downgrades_insufficient_sample_to_weak_and_not_ready():
    rows = []
    for _ in range(2):
        rows.append({"date": "2026-01-01", "region": "Tiny", "revenue": 500})
        rows.append({"date": "2026-02-01", "region": "Tiny", "revenue": 300})
    for _ in range(5):
        rows.append({"date": "2026-01-01", "region": "Big", "revenue": 100})
        rows.append({"date": "2026-02-01", "region": "Big", "revenue": 90})
    state, response = _verified_response(rows, ["region"])

    assert state.leading_dimension == "region"
    assert state.leading_segment == "Tiny"
    assert state.verification_status == "weakened"
    assert state.verification_evidence_strength == "weak"
    assert response.conclusion.readiness.status == "not_ready"
    assert response.conclusion.readiness.reason == "insufficient_evidence"
    assert "insufficient_segment_reliability" in response.conclusion.caveats
    issue = next(item for item in response.data_quality.issues if item.code == "insufficient_segment_sample")
    assert issue.severity == "caution"


def test_segment_reliability_forces_abstention_on_material_structural_absence():
    rows = []
    for _ in range(6):
        rows.append({"date": "2026-01-01", "region": "R", "revenue": 1000})
    for _ in range(5):
        rows.append({"date": "2026-01-01", "region": "Other", "revenue": 100})
        rows.append({"date": "2026-02-01", "region": "Other", "revenue": 95})
    state, response = _verified_response(rows, ["region"])

    assert state.leading_dimension == "region"
    assert state.leading_segment == "R"
    assert state.verification_status == "abstain"
    assert state.verification_evidence_strength == "insufficient"
    assert response.conclusion.readiness.status == "not_ready"
    assert response.conclusion.claim not in {"leading_tested_contributor", "robust_descriptive_explanation"}
    assert response.data_quality.status == "blocked"
    issue = next(item for item in response.data_quality.issues if item.code == "segment_structurally_absent")
    assert issue.severity == "blocking"
    # Row counts must be visible in the public response, not hidden behind the caveat code.
    evidence = next(item for item in response.supporting_evidence if item.evidence_ref in issue.evidence_refs)
    assert evidence.baseline_row_count == 6
    assert evidence.comparison_row_count == 0


def test_segment_reliability_forces_abstention_on_null_baseline_with_no_movement_attributed():
    rows = []
    for _ in range(6):
        rows.append({"date": "2026-01-01", "region": "N", "revenue": None})
        rows.append({"date": "2026-02-01", "region": "N", "revenue": 80})
    for _ in range(5):
        rows.append({"date": "2026-01-01", "region": "Other", "revenue": 100})
        rows.append({"date": "2026-02-01", "region": "Other", "revenue": 100})
    state, response = _verified_response(rows, ["region"])

    assert state.leading_dimension == "region"
    assert state.leading_segment == "N"
    assert state.verification_status == "abstain"
    assert state.verification_evidence_strength == "insufficient"
    assert response.conclusion.readiness.status == "not_ready"
    # "No movement figure attributed": the system does not certify this as a
    # validated finding -- neither claim allows it, and data_quality flags
    # the baseline as unavailable rather than presenting a computed change.
    assert response.conclusion.claim not in {"leading_tested_contributor", "robust_descriptive_explanation"}
    assert response.data_quality.status == "blocked"
    issue = next(item for item in response.data_quality.issues if item.code == "segment_baseline_unavailable")
    assert issue.severity == "blocking"
    evidence = next(item for item in response.supporting_evidence if item.evidence_ref in issue.evidence_refs)
    assert evidence.baseline_row_count == 6
    assert evidence.comparison_row_count == 6


def test_segment_reliability_does_not_alter_outcome_for_a_normal_control_segment():
    rows = []
    for _ in range(6):
        rows.append({"date": "2026-01-01", "region": "Big", "revenue": 100})
        rows.append({"date": "2026-02-01", "region": "Big", "revenue": 70})
        rows.append({"date": "2026-01-01", "region": "Small", "revenue": 50})
        rows.append({"date": "2026-02-01", "region": "Small", "revenue": 48})
    state, response = _verified_response(rows, ["region"])

    assert state.leading_dimension == "region"
    assert state.leading_segment == "Big"
    assert state.verification_status == "robust_no_material_challenge"
    assert state.verification_evidence_strength == "strong"
    assert response.conclusion.readiness.status == "ready_with_caveats"
    assert response.conclusion.claim == "robust_descriptive_explanation"
    assert "insufficient_segment_reliability" not in response.conclusion.caveats
    assert response.data_quality.status == "pass"
    assert response.data_quality.issues == ()
    assert "segment_sample_sufficient" in [item.result_code for item in state.verification_records]


def test_prioritization_rationale_resolves_by_planning_id_not_list_position():
    winning_record = HypothesisPlanningRecord(
        planning_id="IP2",
        allowed_dimensions=("device",),
        validated_proposals=(_hp("HP1", "device", 1, "llm", "Device mix is the current business focus."),),
        planner_mode="llm",
    )
    decoy_record = HypothesisPlanningRecord(
        planning_id="IP1",
        allowed_dimensions=("device",),
        validated_proposals=(_hp("HP1", "device", 1, "llm", "Wrong record: this must never be selected."),),
        planner_mode="llm",
    )
    # Deliberately out of call order: IP2 (the actual match) is listed before
    # IP1, so a positional/first-match resolver would return the decoy text.
    state = _state([winning_record, decoy_record])
    target = InvestigationPathNode(
        node_id="IN2", depth=2, parent_node_id="IN1", planning_id="IP2", selected_dimension="device"
    )

    assert _prioritization_rationale(state, target) == "Device mix is the current business focus."
