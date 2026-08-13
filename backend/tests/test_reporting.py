import base64

from app.domain.contracts import ActionPackage, Recommendation
from app.services.reporting import write_deliverables


def test_case_study_report_is_self_contained_and_escaped(tmp_path):
    chart = tmp_path / "e1.png"
    chart.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    state = {
        "business_question": "Which segment wins <now>?",
        "analysis_summary": "Segment A leads the supplied sample.",
        "analysis_brief": {
            "objective": "Identify the leading segment.",
            "decision": "Choose where to investigate next.",
            "primary_question": "Which segment leads?",
            "stakeholders": [{"name": "Team", "role": "Owner", "decision_interest": "Prioritization"}],
            "success_criteria": ["Rank observed segments."],
            "in_scope": ["Uploaded rows"],
            "out_of_scope": ["Causal inference"],
        },
        "schema_profile": {
            "row_count": 10,
            "column_count": 2,
            "duplicate_row_count": 1,
            "columns": {
                "segment": {"dtype": "object", "semantic_type": "categorical", "null_count": 0, "unique_count": 2},
                "value": {"dtype": "int64", "semantic_type": "numeric", "null_count": 0, "unique_count": 7},
            },
        },
        "source_register": [{"source_id": "S1", "filename": "sales.csv", "format": "CSV", "rows": 10, "columns": 2, "grain": "One sale per row", "licence": "Internal approved source"}],
        "final_summary": {"rows_before": 10, "rows_after": 9},
        "cleaning_log": [{"log_id": "CL1", "action": "Removed exact duplicate", "rows_affected": 1}],
        "integrity_checks": [{"check_id": "IC1", "check": "Row count", "status": "Pass", "detail": "9 retained"}],
        "validation_status": "Pass",
        "quality_findings": [{"issue": "One duplicate", "severity": "medium"}],
        "roccc_answers": {"source_license": "Internal approved source"},
        "analysis_plan": {"operations": [{"operation_id": "OP1", "kind": "grouped_aggregate", "aggregation": "sum", "dimension_column": "segment", "metric_column": "value", "rationale": "Direct comparison"}]},
        "evidence": [{"evidence_id": "E1", "title": "Value by segment", "kind": "grouped_aggregate", "method": "Grouped sum", "population": "9 retained rows", "caveats": []}],
        "findings": [{"finding_id": "F1", "statement": "A leads.", "implication": "Review A first.", "evidence_ids": ["E1"], "confidence": "high", "caveats": []}],
        "chart_paths": {"E1": str(chart)},
        "quality_gates": [{"gate_id": "QG1", "name": "Traceability", "status": "Pass", "severity": "critical", "detail": "Resolved"}],
    }
    package = ActionPackage(
        recommendations=[Recommendation(recommendation_id="R1", action="Review A", rationale="A leads", finding_ids=["F1"], owner_role="Decision owner", timeframe="Next review", expected_impact="unknown", effort="low")],
        limitations=["Descriptive sample only"],
        monitoring_metrics=["Segment value by reporting period"],
    )

    documents = write_deliverables(state, package, tmp_path / "artifacts")

    assert [document.title for document in documents] == ["Case Study Report"]
    report = (tmp_path / "artifacts" / "report.html").read_text(encoding="utf-8")
    assert "Which segment wins &lt;now&gt;?" in report
    assert "Executive Summary" in report
    assert "01 · Ask" in report and "06 · Act" in report
    assert "Ask–Prepare–Process–Analyze–Share–Act" in report
    assert "â" not in report and "Â" not in report
    assert "All data sources used" in report
    assert "Cleaning and manipulation record" in report
    assert "Supporting visualizations and key findings" in report
    assert "Top high-level insights" in report
    assert "Further exploration" in report
    assert "data:image/png;base64," in report
