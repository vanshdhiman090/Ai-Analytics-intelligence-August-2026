"""Health check router — always public, no auth required."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready():
    database_status = "ok"
    data_directory_status = "ok"
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
    except Exception:
        database_status = "unavailable"
    finally:
        if db is not None:
            db.close()

    probe_path: Path | None = None
    try:
        data_dir = Path(settings.DATA_DIR)
        data_dir.mkdir(parents=True, exist_ok=True)
        if not data_dir.is_dir():
            raise OSError("configured data directory is not a directory")
        with NamedTemporaryFile(prefix=".readiness-", dir=data_dir, delete=False) as probe:
            probe.write(b"ready")
            probe_path = Path(probe.name)
    except Exception:
        data_directory_status = "unavailable"
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                data_directory_status = "unavailable"

    payload = {
        "status": "ready" if database_status == data_directory_status == "ok" else "not_ready",
        "database": database_status,
        "data_directory": data_directory_status,
        "checkpointer": settings.CHECKPOINT_BACKEND,
    }
    if payload["status"] != "ready":
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
