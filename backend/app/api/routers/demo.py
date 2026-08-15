"""Bounded recruiter-demo dataset entry point."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from app.api.auth import require_api_key
from app.core.config import settings
from app.core.database import SessionLocal
from app.services.datasets import (
    DatasetProcessingError,
    DatasetRegistrationError,
    DatasetTooLargeError,
    DatasetUploadError,
    register_stored_dataset,
    store_server_fixture,
)


router = APIRouter(
    prefix="/v1/demo",
    tags=["recruiter-demo"],
    dependencies=[Depends(require_api_key)],
)
logger = logging.getLogger(__name__)
HERO_FIXTURE = (
    Path(__file__).resolve().parents[4] / "demo-data" / "rca-revenue-incident.csv"
)


def _error(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": str(getattr(request.state, "request_id", "unknown")),
                "fields": [],
            }
        },
    )


@router.post("/datasets/hero", status_code=status.HTTP_201_CREATED)
def load_hero_dataset(request: Request):
    """Register a fresh governed copy of the maintained hero fixture."""
    if not settings.RECRUITER_DEMO_MODE:
        return _error(
            request,
            status_code=status.HTTP_404_NOT_FOUND,
            code="recruiter_demo_disabled",
            message="Recruiter demo mode is not enabled.",
        )

    stored = None
    try:
        stored = store_server_fixture(
            HERO_FIXTURE,
            settings.DATA_DIR,
            settings.MAX_UPLOAD_BYTES,
        )
        db = SessionLocal()
        try:
            return register_stored_dataset(stored, db)
        finally:
            db.close()
    except FileNotFoundError:
        logger.error(
            "Recruiter demo fixture missing request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return _error(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="demo_dataset_unavailable",
            message="The maintained demo dataset is temporarily unavailable.",
        )
    except (DatasetTooLargeError, DatasetUploadError, DatasetProcessingError, DatasetRegistrationError):
        if stored is not None:
            stored.path.unlink(missing_ok=True)
        logger.exception(
            "Recruiter demo dataset failed request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return _error(
            request,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="demo_dataset_unavailable",
            message="The maintained demo dataset is temporarily unavailable.",
        )
    except Exception:
        if stored is not None:
            stored.path.unlink(missing_ok=True)
        logger.exception(
            "Unexpected recruiter demo dataset failure request_id=%s",
            getattr(request.state, "request_id", "unknown"),
        )
        return _error(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="demo_dataset_unavailable",
            message="The maintained demo dataset is temporarily unavailable.",
        )
