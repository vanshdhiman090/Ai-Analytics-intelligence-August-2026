import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.services.datasets import (
    DatasetTooLargeError,
    DatasetUploadError,
    safe_filename,
    store_upload,
    validate_tabular_file,
)


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


def test_validate_tabular_file_rejects_binary_renamed_as_csv(tmp_path: Path):
    dataset = tmp_path / "renamed.csv"
    dataset.write_bytes(b"PK\x00\x01not-a-csv")
    with pytest.raises(DatasetUploadError, match="CSV is damaged"):
        validate_tabular_file(dataset)


def test_validate_tabular_file_rejects_malformed_workbook(tmp_path: Path):
    dataset = tmp_path / "damaged.xlsx"
    dataset.write_bytes(b"not-an-excel-workbook")
    with pytest.raises(DatasetUploadError, match="Excel file is damaged"):
        validate_tabular_file(dataset)


def test_validate_tabular_file_rejects_header_only_csv(tmp_path: Path):
    dataset = tmp_path / "header-only.csv"
    dataset.write_text("date,revenue,country\n", encoding="utf-8")
    with pytest.raises(DatasetUploadError, match="at least one data row"):
        validate_tabular_file(dataset)


def test_validate_tabular_file_rejects_malformed_content_after_initial_rows(tmp_path: Path):
    dataset = tmp_path / "late-malformed.csv"
    rows = ["segment,revenue", *(f"A,{index}" for index in range(30)), 'B,"unterminated']
    dataset.write_text("\n".join(rows), encoding="utf-8")
    with pytest.raises(DatasetUploadError, match="CSV is damaged"):
        validate_tabular_file(dataset)


def test_validate_tabular_file_accepts_semicolon_windows_csv(tmp_path: Path):
    dataset = tmp_path / "european.csv"
    dataset.write_bytes("region;revenue\nKöln;120,50\nBerlin;95,25\n".encode("cp1252"))
    validate_tabular_file(dataset)


def test_store_upload_accepts_exact_limit_and_rejects_first_byte_over(tmp_path: Path):
    exact = b"value\n1\n"
    stored = asyncio.run(
        store_upload(
            UploadFile(filename="exact.csv", file=BytesIO(exact)),
            tmp_path,
            len(exact),
        )
    )
    assert stored.size_bytes == len(exact)
    assert stored.path.is_file()

    oversized = b"value\n1\n2\n"
    with pytest.raises(DatasetTooLargeError, match="upload limit"):
        asyncio.run(
            store_upload(
                UploadFile(filename="over.csv", file=BytesIO(oversized)),
                tmp_path,
                len(oversized) - 1,
            )
        )
    assert [path.name for path in (tmp_path / "uploads").iterdir()] == [stored.path.name]
