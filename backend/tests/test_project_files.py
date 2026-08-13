import json
import zipfile

from app.services.project_files import create_project_bundle


def test_project_bundle_contains_reproducible_notebook_code_data_and_references(tmp_path):
    cleaned = tmp_path / "cleaned.csv"
    cleaned.write_text("segment,value\nA,10\nB,5\n", encoding="utf-8")
    chart = tmp_path / "e1.png"
    chart.write_bytes(b"png")
    state = {
        "business_question": "Which segment leads?",
        "analysis_summary": "Segment A leads.",
        "original_filename": "sales.csv",
        "source_sha256": "abc123",
        "cleaned_path": str(cleaned),
        "analysis_plan": {"operations": [{"operation_id": "OP1", "kind": "grouped_aggregate", "dimension_column": "segment", "metric_column": "value", "aggregation": "sum"}]},
        "evidence": [{"evidence_id": "E1", "title": "Value by segment"}],
        "findings": [{"finding_id": "F1", "statement": "A leads", "evidence_ids": ["E1"]}],
        "chart_paths": {"E1": str(chart)},
        "source_register": [{"source_id": "S1", "filename": "sales.csv"}],
        "roccc_answers": {"source_license": "Approved internal source"},
    }

    bundle = create_project_bundle(state, tmp_path / "artifacts")
    assert bundle.name == "files.zip"

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert {"analysis.ipynb", "src/reproduce_analysis.py", "data/cleaned.csv", "data/raw-data-reference.json", "config/analysis_plan.json", "charts/e1.png", "outputs/validated_evidence.json", "README.txt"}.issubset(names)
        notebook = json.loads(archive.read("analysis.ipynb"))
        assert notebook["nbformat"] == 4
        assert [cell["cell_type"] for cell in notebook["cells"]].count("code") >= 4
        raw_reference = json.loads(archive.read("data/raw-data-reference.json"))
        assert raw_reference["original_filename"] == "sales.csv"
        assert raw_reference["raw_file_included"] is False
