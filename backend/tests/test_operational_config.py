from __future__ import annotations

import math

import pytest

from app.core.config import settings


def _valid_settings(monkeypatch, tmp_path, *, mode="test"):
    values = {
        "DEPLOYMENT_MODE": mode,
        "DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": "",
        "CHECKPOINT_BACKEND": "memory",
        "CHECKPOINT_POOL_SIZE": 1,
        "RUN_WORKERS": 1,
        "DB_POOL_SIZE": 1,
        "DATA_DIR": tmp_path / "data",
        "MAX_UPLOAD_BYTES": 1024,
        "RECRUITER_DEMO_MODE": False,
        "GUEST_IDENTITY_SECRET": "x" * 32,
        "API_KEYS": set(),
        "FILE_TTL_DAYS": 1,
        "MEMORY_SCOPE": "test-workspace",
        "GOOGLE_CONNECTOR_TIMEOUT_SECONDS": 20.0,
        "CORS_ORIGINS": ["http://127.0.0.1:3010"],
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_valid_test_configuration_allows_provider_fallback_without_api_key(monkeypatch, tmp_path):
    _valid_settings(monkeypatch, tmp_path)
    settings.validate()


def test_recruiter_demo_mode_is_a_typed_boolean(monkeypatch, tmp_path):
    _valid_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "RECRUITER_DEMO_MODE", "true")
    with pytest.raises(RuntimeError, match="RECRUITER_DEMO_MODE"):
        settings.validate()


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("CHECKPOINT_POOL_SIZE", 0),
        ("RUN_WORKERS", -1),
        ("DB_POOL_SIZE", 0),
        ("MAX_UPLOAD_BYTES", 0),
        ("FILE_TTL_DAYS", 0),
    ),
)
def test_nonpositive_operational_limits_fail_predictably(monkeypatch, tmp_path, name, value):
    _valid_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, name, value)
    with pytest.raises(RuntimeError, match=name):
        settings.validate()


@pytest.mark.parametrize("timeout", (0.0, -1.0, 301.0, math.inf))
def test_invalid_connector_timeout_fails_predictably(monkeypatch, tmp_path, timeout):
    _valid_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "GOOGLE_CONNECTOR_TIMEOUT_SECONDS", timeout)
    with pytest.raises(RuntimeError, match="GOOGLE_CONNECTOR_TIMEOUT_SECONDS"):
        settings.validate()


def test_unknown_provider_and_incompatible_checkpoint_database_are_rejected(monkeypatch, tmp_path):
    _valid_settings(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        settings.validate()

    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "CHECKPOINT_BACKEND", "postgres")
    with pytest.raises(RuntimeError, match="PostgreSQL DATABASE_URL"):
        settings.validate()


def test_controlled_pilot_requires_bounded_access_configuration(monkeypatch, tmp_path):
    _valid_settings(monkeypatch, tmp_path, mode="controlled_pilot")
    with pytest.raises(RuntimeError, match="requires API_KEYS"):
        settings.validate()

    monkeypatch.setattr(settings, "API_KEYS", {"short"})
    with pytest.raises(RuntimeError, match="at least 16"):
        settings.validate()

    monkeypatch.setattr(settings, "API_KEYS", {"pilot-key-1234567890"})
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"])
    with pytest.raises(RuntimeError, match="without wildcards"):
        settings.validate()

    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://pilot.example.test"])
    monkeypatch.setattr(settings, "MEMORY_SCOPE", "local-workspace")
    with pytest.raises(RuntimeError, match="unique MEMORY_SCOPE"):
        settings.validate()

    monkeypatch.setattr(settings, "MEMORY_SCOPE", "pilot-workspace-a")
    settings.validate()
