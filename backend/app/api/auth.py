"""API Key authentication dependency.

Rules:
- If `settings.API_KEYS` is empty (default for local dev), all requests pass through.
- If any keys are configured, the `X-API-Key` header must match one of them.
- Health endpoints are always public.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
GUEST_COOKIE_NAME = "rca_guest"
_development_signing_key = secrets.token_bytes(32)


@dataclass(frozen=True)
class GuestPrincipal:
    """Verified anonymous principal derived only from a backend-signed cookie."""

    id: uuid.UUID


def _signing_key() -> bytes:
    configured = settings.GUEST_IDENTITY_SECRET.encode("utf-8")
    return configured or _development_signing_key


def _encode_guest_cookie(guest_id: uuid.UUID) -> str:
    payload = guest_id.hex
    signature = hmac.new(_signing_key(), payload.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{payload}.{encoded_signature}"


def _decode_guest_cookie(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        payload, supplied_signature = value.split(".", 1)
        guest_id = uuid.UUID(hex=payload)
    except (ValueError, AttributeError):
        return None
    expected = _encode_guest_cookie(guest_id).split(".", 1)[1]
    if not hmac.compare_digest(supplied_signature, expected):
        return None
    return guest_id


def guest_principal(request: Request) -> GuestPrincipal:
    """Return one request-stable guest identity, minting it server-side when absent."""
    existing = getattr(request.state, "guest_principal", None)
    if existing is not None:
        return existing
    guest_id = _decode_guest_cookie(request.cookies.get(GUEST_COOKIE_NAME))
    if guest_id is None:
        guest_id = uuid.uuid4()
        request.state.set_guest_cookie = _encode_guest_cookie(guest_id)
    principal = GuestPrincipal(id=guest_id)
    request.state.guest_principal = principal
    return principal


def require_guest_principal(request: Request) -> GuestPrincipal:
    """FastAPI dependency for resources owned by an anonymous guest."""
    return guest_principal(request)


def apply_guest_cookie(response: Response, request: Request) -> None:
    """Emit the guest-identity cookie minted (if any) during this request.

    Production serves the frontend and backend from different registrable
    domains (Vercel / Render), a genuinely cross-site relationship that
    requires SameSite=None; Secure=True. Local/test runs are plain-HTTP
    localhost, where Secure=True would silently drop the cookie instead.
    """
    pending = getattr(request.state, "set_guest_cookie", None)
    if pending is None:
        return
    max_age = 60 * 60 * 24 * 180  # 180 days
    if settings.DEPLOYMENT_MODE == "controlled_pilot":
        response.set_cookie(
            GUEST_COOKIE_NAME, pending, max_age=max_age, path="/",
            httponly=True, secure=True, samesite="none",
        )
    else:
        response.set_cookie(
            GUEST_COOKIE_NAME, pending, max_age=max_age, path="/",
            httponly=True, secure=False, samesite="lax",
        )


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
