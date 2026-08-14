from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services.dataset_lifecycle import (
    cleanup_dataset_records,
    dataset_in_use,
    dataset_record_is_expired,
)
from app.api.main import _cleanup_old_files


class FakeDB:
    def __init__(self):
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0

    def delete(self, item):
        self.deleted.append(item)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _dataset(path: Path, *, created_at: datetime, session_id=None):
    return SimpleNamespace(id=uuid4(), file_path=str(path), created_at=created_at, session_id=session_id)


def test_retention_rule_uses_deterministic_timestamps_and_preserves_recent_or_active_sessions(tmp_path):
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=7)
    old = now - timedelta(days=8)
    recent = now - timedelta(days=1)

    assert dataset_record_is_expired(_dataset(tmp_path / "old.csv", created_at=old), cutoff)
    assert not dataset_record_is_expired(_dataset(tmp_path / "recent.csv", created_at=recent), cutoff)

    session_id = uuid4()
    session_dataset = _dataset(tmp_path / "session.csv", created_at=old, session_id=session_id)
    assert not dataset_record_is_expired(
        session_dataset,
        cutoff,
        session_status="running",
        session_updated_at=old,
    )
    assert not dataset_record_is_expired(
        session_dataset,
        cutoff,
        session_status="complete",
        session_updated_at=recent,
    )
    assert dataset_record_is_expired(
        session_dataset,
        cutoff,
        session_status="complete",
        session_updated_at=old,
    )


def test_cleanup_removes_file_and_row_and_missing_file_is_idempotently_resolved(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    old = datetime(2026, 8, 1, tzinfo=timezone.utc)
    existing_path = data_root / "existing.csv"
    existing_path.write_text("value\n1\n", encoding="utf-8")
    existing = _dataset(existing_path, created_at=old)
    missing = _dataset(data_root / "already-missing.csv", created_at=old)
    db = FakeDB()

    result = cleanup_dataset_records(db, [existing, missing], data_root=data_root)

    assert result.removed == 2
    assert result.missing_files == 1
    assert result.failures == 0
    assert not existing_path.exists()
    assert db.deleted == [existing, missing]
    assert db.commits == 2


def test_active_dataset_is_skipped_until_request_releases_it(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    path = data_root / "active.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    item = _dataset(path, created_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
    db = FakeDB()

    with dataset_in_use(item.id):
        first = cleanup_dataset_records(db, [item], data_root=data_root)
    second = cleanup_dataset_records(db, [item], data_root=data_root)

    assert first.skipped_active == 1
    assert path.exists() is False
    assert second.removed == 1


def test_one_cleanup_failure_does_not_block_other_records_or_leak_path(tmp_path, monkeypatch, caplog):
    data_root = tmp_path / "data"
    data_root.mkdir()
    bad_path = data_root / "private-failing-name.csv"
    good_path = data_root / "good.csv"
    bad_path.write_text("value\n1\n", encoding="utf-8")
    good_path.write_text("value\n1\n", encoding="utf-8")
    old = datetime(2026, 8, 1, tzinfo=timezone.utc)
    bad = _dataset(bad_path, created_at=old)
    good = _dataset(good_path, created_at=old)
    db = FakeDB()
    original_unlink = Path.unlink

    def isolated_failure(path, *args, **kwargs):
        if path.name == bad_path.name:
            raise PermissionError("private failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", isolated_failure)
    result = cleanup_dataset_records(db, [bad, good], data_root=data_root)

    assert result.failures == 1
    assert result.removed == 1
    assert bad_path.exists()
    assert not good_path.exists()
    assert db.rollbacks == 1
    assert str(bad_path) not in caplog.text


def test_cleanup_database_outage_is_observable_but_nonfatal(monkeypatch, caplog):
    monkeypatch.setattr(
        "app.api.main.SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    asyncio.run(_cleanup_old_files(now=datetime(2026, 8, 14, tzinfo=timezone.utc)))
    assert "File cleanup task failed" in caplog.text
