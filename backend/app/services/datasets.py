"""Safe ingestion helpers for user-provided tabular datasets."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from fastapi import UploadFile

from app.services.tabular import read_csv_robust


ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
CHUNK_SIZE = 1024 * 1024


class DatasetUploadError(ValueError):
    """Raised when an uploaded dataset is unsafe or unreadable."""


@dataclass(frozen=True)
class StoredDataset:
    path: Path
    original_filename: str
    content_type: str | None
    size_bytes: int
    sha256: str


def safe_filename(filename: str) -> str:
    """Return a display-safe filename without trusting client path segments."""
    name = Path(filename or "dataset").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "dataset"
    return f"{stem[:100]}{Path(name).suffix.lower()}"


def validate_tabular_file(path: Path) -> None:
    """Parse a small sample so renamed binaries and malformed files are rejected."""
    try:
        if path.suffix == ".csv":
            sample = read_csv_robust(path, nrows=25)
        else:
            sample = pd.read_excel(path, nrows=25)
    except Exception as exc:
        if path.suffix == ".csv":
            message = "The CSV is damaged or uses an unsupported structure. Re-export it as CSV UTF-8 and try again."
        else:
            message = "The Excel file is damaged, password-protected, or not a true .xlsx workbook. Open it in Excel and use Save As → Excel Workbook (.xlsx)."
        raise DatasetUploadError(message) from exc

    if not len(sample.columns):
        raise DatasetUploadError("The dataset must contain at least one column.")
    if any(not str(column).strip() for column in sample.columns):
        raise DatasetUploadError("Every dataset column must have a non-empty name.")


async def store_upload(file: UploadFile, data_dir: Path, max_bytes: int) -> StoredDataset:
    original_filename = safe_filename(file.filename or "dataset")
    extension = Path(original_filename).suffix
    if extension not in ALLOWED_EXTENSIONS:
        raise DatasetUploadError("Only .csv and .xlsx datasets are supported.")

    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{uuid.uuid4().hex}{extension}"
    digest = hashlib.sha256()
    size = 0

    try:
        with destination.open("xb") as output:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > max_bytes:
                    raise DatasetUploadError(
                        f"The dataset exceeds the {max_bytes // (1024 * 1024)} MB upload limit."
                    )
                digest.update(chunk)
                output.write(chunk)

        if size == 0:
            raise DatasetUploadError("The uploaded dataset is empty.")
        validate_tabular_file(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return StoredDataset(
        path=destination,
        original_filename=original_filename,
        content_type=file.content_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
    )
