"""Safe ingestion helpers for user-provided tabular datasets."""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.auth import GuestPrincipal
from app.core.config import settings
from app.models.schema import Dataset
from app.services.tabular import json_value, load_dataframe, profile_dataset


ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
CHUNK_SIZE = 1024 * 1024


class DatasetUploadError(ValueError):
    """Raised when an uploaded dataset is unsafe or unreadable."""


class DatasetTooLargeError(DatasetUploadError):
    """Raised when an upload crosses the server-owned resource boundary."""


class DatasetProcessingError(RuntimeError):
    """Raised when a stored dataset cannot be profiled safely."""


class DatasetRegistrationError(RuntimeError):
    """Raised when a prepared dataset cannot be registered."""


def _display_size_limit(max_bytes: int) -> str:
    if max_bytes >= 1024 * 1024:
        return f"{max_bytes / (1024 * 1024):g} MB"
    if max_bytes >= 1024:
        return f"{max_bytes / 1024:g} KB"
    return f"{max_bytes} bytes"


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
    """Parse the complete file so ordinary malformed input is rejected at upload."""
    try:
        frame = load_dataframe(path)
    except Exception as exc:
        if path.suffix == ".csv":
            message = "The CSV is damaged or uses an unsupported structure. Re-export it as CSV UTF-8 and try again."
        else:
            message = "The Excel file is damaged, password-protected, or not a true .xlsx workbook. Open it in Excel and use Save As → Excel Workbook (.xlsx)."
        raise DatasetUploadError(message) from exc

    if not len(frame.columns):
        raise DatasetUploadError("The dataset must contain at least one column.")
    if any(not str(column).strip() for column in frame.columns):
        raise DatasetUploadError("Every dataset column must have a non-empty name.")
    if frame.empty:
        raise DatasetUploadError("The dataset must contain at least one data row below the header.")


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
                    raise DatasetTooLargeError(
                        f"The dataset exceeds the {_display_size_limit(max_bytes)} upload limit."
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


def store_server_fixture(source: Path, data_dir: Path, max_bytes: int) -> StoredDataset:
    """Copy one server-selected fixture into the governed upload lifecycle."""
    source = source.resolve(strict=True)
    original_filename = safe_filename(source.name)
    extension = source.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DatasetUploadError("The maintained demo dataset has an unsupported format.")
    size = source.stat().st_size
    if size == 0:
        raise DatasetUploadError("The maintained demo dataset is empty.")
    if size > max_bytes:
        raise DatasetTooLargeError(
            f"The maintained demo dataset exceeds the {_display_size_limit(max_bytes)} limit."
        )

    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / f"{uuid.uuid4().hex}{extension}"
    try:
        with source.open("rb") as input_file, destination.open("xb") as output_file:
            shutil.copyfileobj(input_file, output_file, length=CHUNK_SIZE)
        validate_tabular_file(destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return StoredDataset(
        path=destination,
        original_filename=original_filename,
        content_type=(
            "text/csv"
            if extension == ".csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        size_bytes=size,
        sha256=digest,
    )


def owned_dataset_query(db: Session, guest: GuestPrincipal):
    """Scope a Dataset query to rows this guest may see.

    A NULL guest_owner_id (maintained recruiter-demo fixtures, or legacy
    pre-ownership rows) is only visible while RECRUITER_DEMO_MODE is on —
    outside demo mode a NULL owner is never treated as public.
    """
    condition = Dataset.guest_owner_id == guest.id
    if settings.RECRUITER_DEMO_MODE:
        condition = or_(condition, Dataset.guest_owner_id.is_(None))
    return db.query(Dataset).filter(condition)


def register_stored_dataset(
    stored: StoredDataset, db: Session, guest_id: uuid.UUID | None = None
) -> dict:
    """Profile and register a governed file, returning the existing public contract."""
    try:
        profile = profile_dataset(stored.path)
        frame = load_dataframe(stored.path)
        preview = [
            {str(column): json_value(value) for column, value in row.items()}
            for row in frame.head(8).to_dict(orient="records")
        ]
    except Exception as exc:
        raise DatasetProcessingError("The dataset could not be processed.") from exc

    try:
        dataset = Dataset(
            file_path=str(stored.path),
            original_filename=stored.original_filename,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            schema_profile=profile,
            row_count=profile["row_count"],
            guest_owner_id=guest_id,
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
    except Exception as exc:
        db.rollback()
        raise DatasetRegistrationError("The dataset could not be registered.") from exc

    return {
        "dataset_id": str(dataset.id),
        "filename": dataset.original_filename,
        "size_bytes": dataset.size_bytes,
        "profile": profile,
        "preview": preview,
    }
