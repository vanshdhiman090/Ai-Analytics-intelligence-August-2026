"""Application factory — wires routers, middleware, lifespan, and background tasks.

All route logic now lives in app/api/routers/*.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Dataset
from app.models.schema import Session as SessionModel
from app.services import progress as progress_bus
from app.services.run_manager import run_manager

from app.api.routers import agents, health, evaluations, datasets, sessions, artifacts, connectors, rca

logger = logging.getLogger(__name__)


# ── Background tasks ────────────────────────────────────────────────────────

async def _cleanup_old_files() -> None:
    """Delete uploaded/cleaned files for finished sessions older than FILE_TTL_DAYS.

    Runs once per hour. Only removes files for sessions in 'complete' or 'error'
    status — never touches files belonging to active or paused sessions.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.FILE_TTL_DAYS)
    db = SessionLocal()
    try:
        old_datasets = (
            db.query(Dataset)
            .join(SessionModel, Dataset.session_id == SessionModel.id)
            .filter(
                SessionModel.status.in_(["complete", "error"]),
                SessionModel.updated_at < cutoff,
            )
            .all()
        )
        removed = 0
        for dataset in old_datasets:
            path = Path(dataset.file_path)
            if path.exists():
                path.unlink(missing_ok=True)
                removed += 1
        if removed:
            logger.info("File cleanup: removed %d file(s) older than %d days", removed, settings.FILE_TTL_DAYS)
    except Exception:
        logger.exception("File cleanup task failed")
    finally:
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
    progress_bus.set_event_loop(asyncio.get_event_loop())

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
    cleanup_task = asyncio.create_task(_cleanup_loop())

    yield

    cleanup_task.cancel()
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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID", "X-API-Key"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.request_id = request_id
    response = await call_next(request)
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
app.include_router(rca.router)
