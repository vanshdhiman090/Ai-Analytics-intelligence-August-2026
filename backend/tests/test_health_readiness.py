from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings


@asynccontextmanager
async def _no_op_lifespan(_app):
    yield


class ReadyDB:
    def execute(self, _statement):
        return 1

    def close(self):
        pass


def _client():
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    client = TestClient(app)
    client.__enter__()
    return client, original_lifespan


def _close(client, original_lifespan):
    client.__exit__(None, None, None)
    app.router.lifespan_context = original_lifespan


def test_liveness_remains_dependency_light(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.routers.health.SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("database secret")))
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    client, original_lifespan = _client()
    try:
        response = client.get("/health/live")
    finally:
        _close(client, original_lifespan)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_database_failure_is_safe_and_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.routers.health.SessionLocal", lambda: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@private/db")))
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    client, original_lifespan = _client()
    try:
        response = client.get("/health/ready")
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert "secret" not in response.text
    assert "postgresql" not in response.text


def test_readiness_data_directory_failure_is_safe_and_returns_503(tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("private local path", encoding="utf-8")
    monkeypatch.setattr("app.api.routers.health.SessionLocal", ReadyDB)
    monkeypatch.setattr(settings, "DATA_DIR", blocked)
    client, original_lifespan = _client()
    try:
        response = client.get("/health/ready")
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 503
    assert response.json()["data_directory"] == "unavailable"
    assert str(blocked) not in response.text
    assert "private local path" not in response.text


def test_readiness_success_checks_database_and_writable_data_directory(tmp_path, monkeypatch):
    data_dir = tmp_path / "created-by-readiness"
    monkeypatch.setattr("app.api.routers.health.SessionLocal", ReadyDB)
    monkeypatch.setattr(settings, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings, "CHECKPOINT_BACKEND", "memory")
    client, original_lifespan = _client()
    try:
        response = client.get("/health/ready")
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "data_directory": "ok",
        "checkpointer": "memory",
    }
    assert list(data_dir.iterdir()) == []
