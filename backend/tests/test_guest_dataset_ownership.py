from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import GUEST_COOKIE_NAME, _decode_guest_cookie
from app.api.main import app
from app.core.config import settings
from app.models.schema import Base, Dataset

# CI runs the maintained suite against sqlite; the ORM models use Postgres-only
# UUID/JSONB column types, so a schema-creating in-memory test needs sqlite
# type-compilation shims. Production always runs against real Postgres —
# these shims are test-only and never touch the ORM model definitions.
@compiles(UUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "TEXT"


@asynccontextmanager
async def _no_op_lifespan(_app):
    yield


def _session_factory():
    """Fresh in-memory schema-backed session factory, isolated per test."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _client(monkeypatch, factory):
    monkeypatch.setattr("app.api.routers.datasets.SessionLocal", factory)
    monkeypatch.setattr("app.api.routers.sessions.SessionLocal", factory)
    monkeypatch.setattr("app.api.routers.demo.SessionLocal", factory)
    monkeypatch.setattr("app.core.database.SessionLocal", factory)
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    client = TestClient(app)
    client.__enter__()
    return client, original_lifespan


def _close(client, original_lifespan):
    client.__exit__(None, None, None)
    app.router.lifespan_context = original_lifespan
    app.dependency_overrides.clear()


def _upload(client, name="dataset.csv"):
    response = client.post(
        "/datasets",
        files={"file": (name, b"date,revenue\n2026-01-01,10\n2026-02-01,8\n", "text/csv")},
    )
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _seed_dataset(factory, *, guest_owner_id=None, session_id=None):
    db = factory()
    try:
        dataset = Dataset(
            file_path="seeded.csv",
            original_filename="seeded.csv",
            size_bytes=1,
            row_count=1,
            guest_owner_id=guest_owner_id,
            session_id=session_id,
        )
        db.add(dataset)
        db.commit()
        return dataset.id
    finally:
        db.close()


def _rca_payload(dataset_id):
    return {
        "dataset_id": str(dataset_id),
        "goal": "Investigate the revenue decline",
        "kpi": {
            "name": "Revenue",
            "metric_column": "revenue",
            "time_column": "date",
            "time_grain": "month",
            "aggregation": "sum",
            "unit": "EUR",
        },
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country"],
    }


def test_guest_cookie_is_set_once_and_reused_across_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    client, original_lifespan = _client(monkeypatch, factory)
    try:
        first = client.post(
            "/datasets",
            files={"file": ("a.csv", b"date,revenue\n2026-01-01,10\n2026-02-01,8\n", "text/csv")},
        )
        assert first.status_code == 201
        assert GUEST_COOKIE_NAME in first.cookies
        first_guest_id = _decode_guest_cookie(first.cookies[GUEST_COOKIE_NAME])
        assert isinstance(first_guest_id, uuid.UUID)

        second = client.post(
            "/datasets",
            files={"file": ("b.csv", b"date,revenue\n2026-01-01,5\n2026-02-01,4\n", "text/csv")},
        )
        assert second.status_code == 201
        assert GUEST_COOKIE_NAME not in second.cookies
        assert _decode_guest_cookie(client.cookies[GUEST_COOKIE_NAME]) == first_guest_id
    finally:
        _close(client, original_lifespan)


def test_owner_can_upload_then_delete_their_own_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    client, original_lifespan = _client(monkeypatch, factory)
    try:
        dataset_id = _upload(client)
        response = client.delete(f"/datasets/{dataset_id}")
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 204


def test_second_guest_cannot_delete_first_guests_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    client_a, lifespan_a = _client(monkeypatch, factory)
    try:
        dataset_id = _upload(client_a)
    finally:
        _close(client_a, lifespan_a)

    client_b, lifespan_b = _client(monkeypatch, factory)
    try:
        response = client_b.delete(f"/datasets/{dataset_id}")
    finally:
        _close(client_b, lifespan_b)

    assert response.status_code == 404


def test_second_guest_cannot_inspect_first_guests_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    client_a, lifespan_a = _client(monkeypatch, factory)
    try:
        dataset_id = _upload(client_a)
    finally:
        _close(client_a, lifespan_a)

    client_b, lifespan_b = _client(monkeypatch, factory)
    try:
        own_dataset_id = _upload(client_b, name="own.csv")
        response = client_b.post(
            "/data-model/inspect",
            json={"dataset_ids": [dataset_id, own_dataset_id]},
        )
    finally:
        _close(client_b, lifespan_b)

    assert response.status_code == 404


def test_second_guest_cannot_start_rca_on_first_guests_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    owner_id = uuid.uuid4()
    dataset_id = _seed_dataset(factory, guest_owner_id=owner_id)

    client_b, lifespan_b = _client(monkeypatch, factory)
    try:
        response = client_b.post("/v1/rca/investigations", json=_rca_payload(dataset_id))
    finally:
        _close(client_b, lifespan_b)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "dataset_not_found"


def test_second_guest_cannot_claim_first_guests_dataset_into_a_session(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    client_a, lifespan_a = _client(monkeypatch, factory)
    try:
        dataset_id = _upload(client_a)
    finally:
        _close(client_a, lifespan_a)

    client_b, lifespan_b = _client(monkeypatch, factory)
    try:
        response = client_b.post(
            "/sessions",
            json={"dataset_id": dataset_id, "rough_prompt": "Investigate revenue"},
        )
    finally:
        _close(client_b, lifespan_b)

    assert response.status_code == 404
    assert response.json() == {"detail": "One or more datasets were not found"}


def test_null_owner_dataset_is_only_accessible_while_recruiter_demo_mode_is_on(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    factory = _session_factory()
    dataset_id = _seed_dataset(factory, guest_owner_id=None)

    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", False)
    client, original_lifespan = _client(monkeypatch, factory)
    try:
        blocked = client.delete(f"/datasets/{dataset_id}")
    finally:
        _close(client, original_lifespan)
    assert blocked.status_code == 404

    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", True)
    client, original_lifespan = _client(monkeypatch, factory)
    try:
        allowed = client.delete(f"/datasets/{dataset_id}")
    finally:
        _close(client, original_lifespan)
    assert allowed.status_code == 204


def test_hero_demo_dataset_stays_unowned(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", True)
    factory = _session_factory()
    client, original_lifespan = _client(monkeypatch, factory)
    try:
        response = client.post("/v1/demo/datasets/hero")
        assert response.status_code == 201, response.text
        dataset_id = uuid.UUID(response.json()["dataset_id"])
    finally:
        _close(client, original_lifespan)

    db = factory()
    try:
        row = db.query(Dataset).filter(Dataset.id == dataset_id).first()
        assert row is not None
        assert row.guest_owner_id is None
    finally:
        db.close()
