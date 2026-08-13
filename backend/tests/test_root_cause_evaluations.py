import copy
import json

from app.evals.root_cause_runner import (
    CASES_PATH,
    REFERENCE_PREDICTIONS_PATH,
    combine_with_analytical_release,
    evaluate,
    load_cases,
    load_predictions,
    score_case,
    write_reports,
)


EXPECTED_METRICS = {
    "anomaly_detection",
    "incident_classification",
    "primary_branch",
    "affected_segment",
    "contribution_accuracy",
    "hypothesis_status_accuracy",
    "correct_abstention",
    "explained_impact_reconciliation",
    "causal_claim_safety",
    "evidence_traceability",
}


def _case_and_prediction(case_id: str):
    _, cases = load_cases()
    predictions = load_predictions(REFERENCE_PREDICTIONS_PATH)
    return (
        copy.deepcopy(next(case for case in cases if case["id"] == case_id)),
        copy.deepcopy(next(item for item in predictions if item["case_id"] == case_id)),
    )


def test_root_cause_suite_has_ten_answer_keyed_incidents():
    version, cases = load_cases(CASES_PATH)

    assert version == "1.0"
    assert len(cases) == 10
    assert {case["expected"]["incident_type"] for case in cases} == {
        "business_incident",
        "data_incident",
        "normal_variation",
        "insufficient_evidence",
    }
    assert any(len(case["expected"]["primary_branches"]) > 1 for case in cases)
    assert any(case["expected"]["must_abstain"] for case in cases)


def test_reference_predictions_calibrate_every_score_at_one():
    summary, results = evaluate()

    assert summary["release_ready"] is True
    assert summary["overall_score"] == 1.0
    assert summary["passed_count"] == 10
    assert set(summary["metric_scores"]) == EXPECTED_METRICS
    assert all(score == 1.0 for score in summary["metric_scores"].values())
    assert all(result.passed for result in results)


def test_scorer_detects_wrong_incident_branch_segment_contribution_and_hypotheses():
    case, prediction = _case_and_prediction("RCA-001")
    prediction.update(
        {
            "incident_type": "data_incident",
            "primary_branches": ["traffic"],
            "affected_segments": [{"country": "France", "device": "desktop"}],
            "abstained": True,
            "reconciliation": {"total_movement": -10000, "explained_movement": -6000, "unexplained_movement": 0},
        }
    )
    prediction["contributions"][0]["absolute_impact"] = -3000
    prediction["hypotheses"][0]["status"] = "rejected"

    result = score_case(case, prediction)
    scores = {metric.metric: metric.score for metric in result.metrics}

    assert result.passed is False
    assert scores["incident_classification"] == 0.0
    assert scores["primary_branch"] == 0.0
    assert scores["affected_segment"] == 0.0
    assert scores["contribution_accuracy"] == 0.0
    assert scores["hypothesis_status_accuracy"] < 1.0
    assert scores["correct_abstention"] == 0.0
    assert scores["explained_impact_reconciliation"] < 1.0


def test_scorer_blocks_unsupported_causal_wording_and_broken_evidence_links():
    case, prediction = _case_and_prediction("RCA-003")
    prediction["conclusion"] = "Paid social caused the order decline."
    prediction["findings"][0]["evidence_ids"] = ["E999"]

    result = score_case(case, prediction)
    scores = {metric.metric: metric.score for metric in result.metrics}

    assert scores["causal_claim_safety"] == 0.0
    assert scores["evidence_traceability"] < 1.0
    assert result.passed is False


def test_missing_prediction_fails_closed():
    case, _ = _case_and_prediction("RCA-010")

    result = score_case(case, None)

    assert result.passed is False
    assert result.error == "prediction missing"
    assert all(metric.score == 0.0 for metric in result.metrics)


def test_root_cause_reports_are_machine_and_human_readable(tmp_path):
    summary, results = evaluate()
    json_path, html_path = write_reports(summary, results, tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["overall_score"] == 1.0
    assert len(payload["cases"]) == 10
    assert "Controlled Root Cause Evaluation" in html_path.read_text(encoding="utf-8")


def test_integration_hook_preserves_legacy_categories_and_requires_both_gates():
    analytical = {
        "release_ready": True,
        "case_count": 28,
        "passed_count": 28,
        "failed_count": 0,
        "category_scores": {"calculation": 1.0, "safety": 1.0},
    }
    root_cause, _ = evaluate()

    combined = combine_with_analytical_release(analytical, root_cause)

    assert combined["release_ready"] is True
    assert combined["case_count"] == 38
    assert combined["category_scores"] == analytical["category_scores"]
    assert combined["root_cause_gate"]["metric_scores"].keys() == EXPECTED_METRICS

