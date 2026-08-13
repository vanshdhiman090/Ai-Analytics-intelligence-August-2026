"""API Key authentication dependency.

Rules:
- If `settings.API_KEYS` is empty (default for local dev), all requests pass through.
- If any keys are configured, the `X-API-Key` header must match one of them.
- Health endpoints are always public.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency: enforce API key when keys are configured."""
    if not settings.API_KEYS:
        # Auth is disabled (local dev mode — no API_KEYS env var set)
        return
    if not api_key or api_key not in settings.API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
