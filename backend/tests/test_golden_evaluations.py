import json

from app.evals.runner import evaluate, run_suite, write_reports


def test_all_golden_cases_pass():
    results = run_suite()
    assert results
    assert all(item["passed"] for item in results), results


def test_release_gate_is_ready_only_when_every_layer_passes():
    summary, results = evaluate()
    assert summary["release_ready"] is True
    assert summary["weighted_score"] == 1.0
    assert summary["critical_failures"] == []
    assert set(summary["category_scores"]) == {"calculation", "data_quality", "methodology", "safety", "uncertainty"}
    assert len(results) >= 20


def test_evaluation_writes_machine_and_human_readable_reports(tmp_path):
    summary, results = evaluate()
    json_path, html_path = write_reports(summary, results, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["release_ready"] is True
    assert len(payload["cases"]) == summary["case_count"]
    assert "Analytics Accuracy & Regression Evaluation" in html_path.read_text(encoding="utf-8")
