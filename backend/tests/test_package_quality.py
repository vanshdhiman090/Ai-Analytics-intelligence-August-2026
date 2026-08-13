import pytest

from app.agent.package_node import validate_package
from app.domain.contracts import ActionPackage, Recommendation


def action_package():
    return ActionPackage(recommendations=[Recommendation(recommendation_id="R1", action="Review segment A", rationale="It has the highest observed total", finding_ids=["F1"], owner_role="Decision owner", timeframe="Next review", expected_impact="unknown", effort="low")], limitations=["Descriptive sample"], monitoring_metrics=["Value by segment"])


def complete_plan():
    return {"operations": [{"operation_id": "OP1", "kind": "grouped_aggregate"}]}


def test_package_quality_gates_accept_traceable_descriptive_output(tmp_path):
    chart = tmp_path / "e1.png"
    chart.write_bytes(b"chart")
    state = {"analysis_plan": complete_plan(), "analysis_summary": "Segment A has the highest observed total.", "evidence": [{"evidence_id": "E1", "population": "9 retained rows", "kind": "grouped_aggregate"}], "findings": [{"finding_id": "F1", "statement": "Segment A has the highest total", "implication": "Review A first", "confidence": "high", "evidence_ids": ["E1"]}], "chart_paths": {"E1": str(chart)}, "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": [{"check_id": "IC1", "status": "Pass"}], "validation_status": "Pass"}
    gates = validate_package(state, action_package())
    assert all(item["status"] == "Pass" for item in gates)


def test_package_quality_gates_block_unsupported_causal_claims():
    state = {"analysis_summary": "Segment A is highest.", "evidence": [{"evidence_id": "E1", "population": "9 retained rows"}], "findings": [{"finding_id": "F1", "statement": "Segment A causes higher value", "implication": "Review A first", "confidence": "high", "evidence_ids": ["E1"]}], "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": []}
    with pytest.raises(ValueError, match="quality gate"):
        validate_package(state, action_package())


def test_segment_change_contribution_wording_is_not_treated_as_causal():
    state = {
        "analysis_plan": complete_plan(),
        "analysis_summary": "Segment A contributed to observed movement.",
        "evidence": [{"evidence_id": "E1", "population": "9 retained rows", "kind": "segment_change"}],
        "findings": [{"finding_id": "F1", "statement": "Segment A drives the observed change", "implication": "Review A's contribution", "confidence": "medium", "evidence_ids": ["E1"]}],
        "roccc_answers": {"source_license": "Internal approved source"},
        "integrity_checks": [],
        "validation_status": "Pass",
    }
    gates = validate_package(state, action_package())
    causal_gate = next(item for item in gates if item["gate_id"] == "QG4")
    assert causal_gate["status"] == "Pass"


def test_package_quality_gates_block_orphan_chart(tmp_path):
    chart = tmp_path / "orphan.png"
    chart.write_bytes(b"chart")
    state = {"analysis_plan": complete_plan(), "analysis_summary": "Segment A is highest.", "evidence": [{"evidence_id": "E1", "population": "9 retained rows"}], "findings": [{"finding_id": "F1", "statement": "Segment A is highest", "implication": "Review A first", "confidence": "high", "evidence_ids": ["E1"]}], "chart_paths": {"E99": str(chart)}, "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": [], "validation_status": "Pass"}

    with pytest.raises(ValueError, match="Orphan chart IDs"):
        validate_package(state, action_package())


def test_missing_visual_is_advisory_not_publication_blocker():
    state = {"analysis_plan": complete_plan(), "analysis_summary": "Segment A is highest.", "evidence": [{"evidence_id": "E1", "population": "9 retained rows", "kind": "grouped_aggregate"}], "findings": [{"finding_id": "F1", "statement": "Segment A is highest", "implication": "Review A first", "confidence": "high", "evidence_ids": ["E1"]}], "chart_paths": {}, "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": [], "validation_status": "Pass"}

    gates = validate_package(state, action_package())

    visual_gate = next(item for item in gates if item["gate_id"] == "QG8")
    assert visual_gate["status"] == "Fail"
    assert visual_gate["severity"] == "advisory"


def test_empty_analysis_can_never_pass_publication():
    state = {"analysis_plan": {"operations": []}, "analysis_summary": "Unable to analyze.", "evidence": [], "findings": [], "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": [], "validation_status": "Pass"}
    empty_package = ActionPackage(recommendations=[], limitations=["No validated analysis"], monitoring_metrics=[])

    with pytest.raises(ValueError, match="Publication blocked"):
        validate_package(state, empty_package)


def test_package_blocks_narrative_that_denies_available_segment_evidence():
    state = {
        "analysis_plan": complete_plan(),
        "comparison_context": {"baseline_period": "2021-09", "comparison_period": "2021-10"},
        "analysis_summary": "Segment decomposition is unavailable for this comparison.",
        "evidence": [{"evidence_id": "E1", "population": "9 retained rows", "kind": "segment_change", "diagnostics": {"baseline_period": "2021-09", "comparison_period": "2021-10"}}],
        "findings": [{"finding_id": "F1", "statement": "Segment A contributed to observed movement", "implication": "Review A", "confidence": "medium", "evidence_ids": ["E1"]}],
        "roccc_answers": {"source_license": "Internal approved source"}, "integrity_checks": [], "validation_status": "Pass",
    }
    with pytest.raises(ValueError, match="narrative says segment decomposition"):
        validate_package(state, action_package())
