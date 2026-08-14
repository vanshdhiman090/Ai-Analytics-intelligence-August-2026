"""Bounded local lifecycle controls for uploaded dataset records and files."""

from __future__ import annotations

import logging
import threading
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from sqlalchemy.orm import Session

from app.models.schema import Dataset
from app.models.schema import Session as SessionModel


logger = logging.getLogger(__name__)
_active_lock = threading.Lock()
_active_datasets: Counter[str] = Counter()


@contextmanager
def dataset_in_use(dataset_id: Any) -> Iterator[None]:
    """Protect a dataset from this process's cleanup while a request uses it."""
    key = str(dataset_id)
    with _active_lock:
        _active_datasets[key] += 1
    try:
        yield
    finally:
        with _active_lock:
            _active_datasets[key] -= 1
            if _active_datasets[key] <= 0:
                _active_datasets.pop(key, None)


def dataset_is_in_use(dataset_id: Any) -> bool:
    with _active_lock:
        return _active_datasets[str(dataset_id)] > 0


def dataset_record_is_expired(
    dataset: Dataset,
    cutoff: datetime,
    *,
    session_status: str | None = None,
    session_updated_at: datetime | None = None,
) -> bool:
    """Apply the retention rule independently of wall-clock time and SQL."""
    if dataset.created_at is None or dataset.created_at >= cutoff:
        return False
    if dataset.session_id is None:
        return True
    return (
        session_status in {"complete", "error"}
        and session_updated_at is not None
        and session_updated_at < cutoff
    )


def expired_dataset_records(db: Session, cutoff: datetime) -> list[Dataset]:
    """Return old standalone uploads and old datasets from finished sessions."""
    rows = (
        db.query(Dataset, SessionModel.status, SessionModel.updated_at)
        .outerjoin(SessionModel, Dataset.session_id == SessionModel.id)
        .filter(Dataset.created_at < cutoff)
        .all()
    )
    return [
        dataset
        for dataset, session_status, session_updated_at in rows
        if dataset_record_is_expired(
            dataset,
            cutoff,
            session_status=session_status,
            session_updated_at=session_updated_at,
        )
    ]


@dataclass(frozen=True)
class DatasetCleanupResult:
    removed: int = 0
    missing_files: int = 0
    skipped_active: int = 0
    failures: int = 0


def cleanup_dataset_records(
    db: Session,
    datasets: Iterable[Dataset],
    *,
    data_root: Path,
) -> DatasetCleanupResult:
    """Delete eligible local files and rows independently and idempotently."""
    root = data_root.resolve()
    removed = missing_files = skipped_active = failures = 0

    for dataset in datasets:
        dataset_id = str(dataset.id)
        if dataset_is_in_use(dataset_id):
            skipped_active += 1
            continue
        try:
            path = Path(dataset.file_path).resolve()
            if not path.is_relative_to(root):
                raise ValueError("dataset path is outside the governed data directory")
            missing = not path.exists()
            if not missing:
                path.unlink()
            db.delete(dataset)
            db.commit()
            removed += 1
            missing_files += int(missing)
        except Exception:
            db.rollback()
            failures += 1
            logger.exception("Dataset cleanup failed dataset_id=%s", dataset_id)

    return DatasetCleanupResult(
        removed=removed,
        missing_files=missing_files,
        skipped_active=skipped_active,
        failures=failures,
    )
