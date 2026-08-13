import zipfile

import pytest

from app.domain.contracts import ActionPackage, Recommendation
from app.services.presentation_deck import create_stakeholder_pptx, presentation_runtime_available


@pytest.mark.skipif(not presentation_runtime_available(), reason="Native presentation runtime is unavailable")
def test_native_powerpoint_contains_editable_chart_and_source_notes(tmp_path):
    state = {
        "session_id": "test-session",
        "business_question": "Which segment should receive priority?",
        "analysis_summary": "Segment A leads observed revenue.",
        "analysis_brief": {"objective": "Compare segments", "decision": "Prioritize follow-up"},
        "schema_profile": {"row_count": 10, "column_count": 2},
        "source_register": [{"filename": "sales.csv", "rows": 10, "columns": 2, "grain": "One sale per row"}],
        "roccc_answers": {"source_license": "Approved internal source"},
        "validation_status": "Pass",
        "evidence": [{"evidence_id": "E1", "kind": "grouped_aggregate", "title": "sum of Revenue by Segment", "rows": [{"Segment": "A", "value": 100}, {"Segment": "B", "value": 60}], "population": "10 retained rows", "method": "Grouped sum", "caveats": []}],
        "findings": [{"finding_id": "F1", "statement": "Segment A leads revenue.", "implication": "Review Segment A first.", "confidence": "high", "evidence_ids": ["E1"], "caveats": []}],
        "original_filename": "sales.csv",
    }
    package = ActionPackage(
        recommendations=[Recommendation(recommendation_id="R1", action="Review Segment A", rationale="A leads", finding_ids=["F1"], owner_role="Decision owner", timeframe="Next review", expected_impact="unknown", effort="low")],
        limitations=["Descriptive sample only."],
        monitoring_metrics=["Revenue by segment"],
    )

    output = create_stakeholder_pptx(state, package, tmp_path / "artifacts")

    assert output.name == "deck.pptx"
    with zipfile.ZipFile(output) as deck:
        names = set(deck.namelist())
        assert "ppt/presentation.xml" in names
        assert any(name.startswith("ppt/slides/charts/chart") and name.endswith(".xml") for name in names)
        assert any(name.startswith("ppt/notesSlides/notesSlide") and name.endswith(".xml") for name in names)
