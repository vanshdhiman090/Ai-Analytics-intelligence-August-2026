from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routers.rca import get_rca_dataset_resolver
from app.core.config import settings


@asynccontextmanager
async def _no_op_lifespan(_app):
    yield


class _MemorySession:
    def __init__(self, records):
        self.records = records

    def add(self, record):
        if record.id is None:
            record.id = uuid4()
        self.records.append(record)

    def commit(self):
        return None

    def rollback(self):
        return None

    def refresh(self, _record):
        return None

    def close(self):
        return None


def _client():
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _no_op_lifespan
    client = TestClient(app)
    client.__enter__()
    return client, original_lifespan


def _close(client, original_lifespan):
    client.__exit__(None, None, None)
    app.router.lifespan_context = original_lifespan
    app.dependency_overrides.clear()


def _rca_payload(dataset_id):
    return {
        "dataset_id": dataset_id,
        "goal": "Investigate why Revenue changed in the maintained demo fixture.",
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
        "candidate_dimensions": ["country", "device", "customer_type"],
    }


def test_demo_endpoint_registers_opaque_fixture_and_runs_real_rca(tmp_path, monkeypatch):
    records = []
    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", True)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr("app.api.routers.demo.SessionLocal", lambda: _MemorySession(records))
    provider_failure = lambda *_: (_ for _ in ()).throw(TimeoutError("provider unavailable"))
    monkeypatch.setattr("app.services.hypothesis_planner.generate_structured", provider_failure)
    monkeypatch.setattr("app.services.investigation_controller.generate_structured", provider_failure)
    monkeypatch.setattr("app.services.investigation_verifier.generate_structured", provider_failure)

    client, original_lifespan = _client()
    try:
        loaded = client.post(
            "/v1/demo/datasets/hero",
            headers={"X-Request-ID": "demo-load-1"},
        )
        assert loaded.status_code == 201, loaded.text
        body = loaded.json()
        dataset_id = UUID(body["dataset_id"])
        assert body["filename"] == "rca-revenue-incident.csv"
        assert body["profile"]["row_count"] == 320
        assert "file_path" not in loaded.text
        assert str(tmp_path) not in loaded.text
        assert len(records) == 1
        assert records[0].id == dataset_id
        stored_path = Path(records[0].file_path)
        assert stored_path.is_relative_to(tmp_path.resolve())
        assert stored_path.name != "rca-revenue-incident.csv"

        app.dependency_overrides[get_rca_dataset_resolver] = lambda: (
            lambda requested_id: records[0]
            if requested_id == dataset_id
            else (_ for _ in ()).throw(RuntimeError("unexpected dataset id"))
        )
        investigated = client.post(
            "/v1/rca/investigations",
            json=_rca_payload(str(dataset_id)),
            headers={"X-Request-ID": "demo-rca-1"},
        )
    finally:
        _close(client, original_lifespan)

    assert investigated.status_code == 200, investigated.text
    result = investigated.json()
    assert [step["segment"] for step in result["investigation_path"]] == [
        "Germany",
        "Mobile",
        "Returning",
    ]
    assert result["kpi_movement"]["baseline_value"] == 16000.0
    assert result["kpi_movement"]["comparison_value"] == 14600.0
    assert result["kpi_movement"]["signed_change"] == -1400.0
    assert result["leading_contributor"]["signed_change"] == -1400.0
    assert round(result["leading_contributor"]["local_contribution_pct"], 1) == 127.3
    assert result["selected_decomposition"]["positive_offsets"] == 300.0
    assert result["selected_decomposition"]["reconciliation_residual"] == 0.0
    assert result["conclusion"]["claim"] == "leading_tested_contributor"
    assert result["conclusion"]["readiness"]["status"] == "ready_with_caveats"
    assert result["conclusion"]["robustness"] == {
        "status": "not_verified",
        "applies_to_selected_target": False,
    }
    assert "confirmed root cause" not in investigated.text.lower()


def test_arbitrary_upload_is_rejected_server_side_in_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", True)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    client, original_lifespan = _client()
    try:
        response = client.post(
            "/datasets",
            files={"file": ("outside.csv", b"date,revenue\n2026-01-01,1\n", "text/csv")},
            headers={"X-Request-ID": "blocked-upload-1"},
        )
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 403
    assert response.headers["X-Request-ID"] == "blocked-upload-1"
    assert response.json()["error"] == {
        "code": "external_dataset_ingestion_disabled",
        "message": "External dataset upload is not available in recruiter demo mode.",
        "request_id": "blocked-upload-1",
        "fields": [],
    }
    assert not (tmp_path / "uploads").exists()


def test_normal_upload_remains_available_outside_demo_mode(tmp_path, monkeypatch):
    records = []
    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", False)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr("app.api.routers.datasets.SessionLocal", lambda: _MemorySession(records))
    client, original_lifespan = _client()
    try:
        response = client.post(
            "/datasets",
            files={
                "file": (
                    "local.csv",
                    b"date,revenue,country\n2026-01-01,10,Germany\n2026-02-01,8,Germany\n",
                    "text/csv",
                )
            },
        )
    finally:
        _close(client, original_lifespan)

    assert response.status_code == 201, response.text
    assert UUID(response.json()["dataset_id"])
    assert response.json()["filename"] == "local.csv"
    assert response.json()["profile"]["row_count"] == 2
    assert len(records) == 1
