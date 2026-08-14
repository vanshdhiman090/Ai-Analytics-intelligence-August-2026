from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.config import settings


@asynccontextmanager
async def _no_op_lifespan(_app):
    yield


def _client():
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    client = TestClient(app)
    client.__enter__()
    return client, original_lifespan


def _close(client, original_lifespan):
    client.__exit__(None, None, None)
    app.router.lifespan_context = original_lifespan


def test_unsupported_upload_is_structured_and_request_id_correlated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    client, original_lifespan = _client()
    try:
        response = client.post(
            "/datasets",
            files={"file": ("notes.txt", b"not tabular", "text/plain")},
            headers={"X-Request-ID": "bad-upload-1"},
        )
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "bad-upload-1"
    assert response.json() == {
        "error": {
            "code": "invalid_dataset",
            "message": "Only .csv and .xlsx datasets are supported.",
            "request_id": "bad-upload-1",
            "fields": [],
        }
    }
    assert not (tmp_path / "uploads").exists()


def test_header_only_upload_is_rejected_without_creating_a_dataset_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    client, original_lifespan = _client()
    try:
        response = client.post(
            "/datasets",
            files={"file": ("header-only.csv", b"date,revenue\n", "text/csv")},
        )
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_dataset"
    assert "at least one data row" in response.json()["error"]["message"]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_oversized_upload_stops_with_413_and_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 8)
    client, original_lifespan = _client()
    try:
        response = client.post(
            "/datasets",
            files={"file": ("large.csv", b"value\n1\n2\n", "text/csv")},
            headers={"X-Request-ID": "large-upload-2"},
        )
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 413
    assert response.json()["error"] == {
        "code": "dataset_too_large",
        "message": "The dataset exceeds the 8 bytes upload limit.",
        "request_id": "large-upload-2",
        "fields": [],
    }
    assert list((tmp_path / "uploads").iterdir()) == []
