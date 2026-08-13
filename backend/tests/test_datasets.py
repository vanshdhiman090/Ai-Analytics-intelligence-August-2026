from pathlib import Path

import pytest

from app.services.datasets import DatasetUploadError, safe_filename, validate_tabular_file


def test_safe_filename_removes_client_paths_and_unsafe_characters():
    assert safe_filename("../../Quarter 1 sales?.CSV") == "Quarter_1_sales.csv"


def test_validate_tabular_file_accepts_csv_with_headers(tmp_path: Path):
    dataset = tmp_path / "valid.csv"
    dataset.write_text("segment,revenue\nA,100\nB,120\n", encoding="utf-8")
    validate_tabular_file(dataset)


def test_validate_tabular_file_rejects_malformed_csv(tmp_path: Path):
    dataset = tmp_path / "invalid.csv"
    dataset.write_bytes(b'"unterminated')
    with pytest.raises(DatasetUploadError, match="CSV is damaged"):
        validate_tabular_file(dataset)


def test_validate_tabular_file_accepts_semicolon_windows_csv(tmp_path: Path):
    dataset = tmp_path / "european.csv"
    dataset.write_bytes("region;revenue\nKöln;120,50\nBerlin;95,25\n".encode("cp1252"))
    validate_tabular_file(dataset)
