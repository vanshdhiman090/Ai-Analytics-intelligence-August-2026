import pandas as pd

from app.services.tabular import process_dataset


def test_processing_creates_reconciled_cleaning_and_integrity_audit(tmp_path):
    source = tmp_path / "source.csv"
    pd.DataFrame({"customer_id": [1, 1, 2], "segment": [" A ", " A ", "B"], "value": [10, 10, -2]}).to_csv(source, index=False)

    result = process_dataset(source, tmp_path / "cleaned.csv")

    assert result.summary["rows_before"] == 3
    assert result.summary["rows_after"] == 2
    assert any(item["action"] == "Remove exact duplicate records" and item["rows_affected"] == 1 for item in result.cleaning_log)
    assert any(item["check"] == "Row-count reconciliation" and item["status"] == "Pass" for item in result.integrity_checks)
    assert any(item["check"] == "Numeric sign review: value" and item["status"] == "Warning" for item in result.integrity_checks)
    assert result.validation_status == "Warning"
