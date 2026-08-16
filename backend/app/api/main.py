"""Application factory — wires routers, middleware, lifespan, and background tasks.

All route logic now lives in app/api/routers/*.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func

from app.api.auth import apply_guest_cookie
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel
from app.services import progress as progress_bus
from app.services.dataset_lifecycle import cleanup_dataset_records, expired_dataset_records
from app.services.run_manager import run_manager

from app.api.routers import agents, health, evaluations, datasets, sessions, artifacts, connectors, demo, rca

logger = logging.getLogger(__name__)


# ── Background tasks ────────────────────────────────────────────────────────

async def _cleanup_old_files(*, now: datetime | None = None) -> None:
    """Remove expired standalone and finished-session dataset files and rows.

    Runs once per hour. Recent standalone uploads and active-session datasets are preserved;
    active in-process RCA requests are skipped.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=settings.FILE_TTL_DAYS)
    db = None
    try:
        db = SessionLocal()
        result = cleanup_dataset_records(
            db,
            expired_dataset_records(db, cutoff),
            data_root=settings.DATA_DIR,
        )
        if result.removed or result.skipped_active or result.failures:
            logger.info(
                "Dataset cleanup: removed=%d missing_files=%d skipped_active=%d failures=%d ttl_days=%d",
                result.removed,
                result.missing_files,
                result.skipped_active,
                result.failures,
                settings.FILE_TTL_DAYS,
            )
    except Exception:
        logger.exception("File cleanup task failed")
    finally:
        if db is not None:
            db.close()


async def _cleanup_loop() -> None:
    """Run file cleanup every hour indefinitely."""
    while True:
        await asyncio.sleep(3600)
        await _cleanup_old_files()


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.validate()

    # Register the running event loop with the SSE progress bus so worker
    # threads can schedule events onto it.
    progress_bus.set_event_loop(asyncio.get_running_loop())

    # Mark any sessions that were interrupted by a previous crash as failed.
    db = SessionLocal()
    try:
        interrupted = (
            db.query(SessionModel)
            .filter(SessionModel.status.in_(["queued", "running", "active"]))
            .all()
        )
        for session in interrupted:
            session.status = "error"
            session.error_message = (
                "The previous process stopped before this run finished. Retry is available."
            )
            session.updated_at = func.now()
        db.commit()
    finally:
        db.close()

    # Start the hourly file cleanup background task.
    cleanup_task = asyncio.create_task(_cleanup_loop(), name="dataset-cleanup")

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        run_manager.shutdown()


# ── App factory ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Analytics Workspace API",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
    apply_guest_cookie(response, request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


# ── Register routers ────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(evaluations.router)
app.include_router(datasets.router)
app.include_router(sessions.router)
app.include_router(artifacts.router)
app.include_router(agents.router)
app.include_router(connectors.router)
app.include_router(demo.router)
app.include_router(rca.router)
