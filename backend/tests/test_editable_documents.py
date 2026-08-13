from types import SimpleNamespace

from docx import Document

from app.services.editable_documents import build_docx, build_pdf, seed_document


def test_seed_and_export_editable_case_study_report(tmp_path):
    session = SimpleNamespace(
        business_task="Which region leads revenue?",
        result_summary={
            "summary": "North leads the supplied sample.",
            "analysis_brief": {"primary_question": "Which region leads revenue?", "objective": "Rank regions", "decision": "Prioritize a region"},
            "findings": [{"finding_id": "F1", "statement": "North leads.", "implication": "Review North.", "evidence_ids": ["E1"]}],
            "recommendations": [{"recommendation_id": "R1", "action": "Review North", "rationale": "It leads", "owner_role": "Analyst", "timeframe": "Next review"}],
            "limitations": ["Descriptive sample only"],
            "monitoring_metrics": ["Revenue by region"],
            "unanswered_questions": [],
        },
    )
    dataset = SimpleNamespace(original_filename="sales.csv", schema_profile={"row_count": 10, "column_count": 3, "duplicate_row_count": 0, "columns": {}})
    content = seed_document("Case Study Report", session, dataset, [], [], "case_study_report")
    content["sections"][0]["body"] = "North leads after human review."
    output = build_docx(content, tmp_path / "edited.docx")
    reopened = Document(output)
    text = "\n".join(paragraph.text for paragraph in reopened.paragraphs)
    assert "North leads after human review." in text
    assert "Which region leads revenue?" in text
    assert "Executive Summary" in text
    assert "01 Â· Ask" in text and "06 Â· Act" in text
    assert reopened.core_properties.title == "Which region leads revenue?"
    assert reopened.core_properties.author == "AI Analytics Workspace"
    assert content["schema_version"] == "2.0"
    assert content["document_type"] == "case_study_report"
    assert any(block["type"] == "table" for section in content["sections"] for block in section.get("blocks", []))
    pdf = build_pdf(content, tmp_path / "edited.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
