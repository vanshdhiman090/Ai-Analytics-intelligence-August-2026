"""Health check router — always public, no auth required."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {
            "status": "ready",
            "database": "ok",
            "checkpointer": settings.CHECKPOINT_BACKEND,
        }
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database is not ready") from exc
    finally:
        db.close()
