"""Sessions router — create, list, get, resume, retry, SSE progress stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import AsyncGenerator, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func

from app.api.auth import GuestPrincipal, require_api_key, require_guest_principal
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import AgentAction, Artifact, Checkpoint, Dataset, DocumentRevision
from app.models.schema import Session as SessionModel
from app.services import progress as progress_bus
from app.services.data_model import DataModelError, ModelSource, materialize_data_model
from app.services.datasets import owned_dataset_query
from app.services.run_manager import run_manager

router = APIRouter(tags=["sessions"], dependencies=[Depends(require_api_key)])


# ── Request / response models ───────────────────────────────────────────────

class JoinRequest(BaseModel):
    relationship_id: str = Field(min_length=3, max_length=500)


class CreateSessionRequest(BaseModel):
    dataset_id: uuid.UUID | None = None
    dataset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    joins: list[JoinRequest] = Field(default_factory=list, max_length=9)
    analysis_objectives: list[Literal["drivers", "trends", "segments", "quality", "root_cause"]] = Field(
        default_factory=list, max_length=5
    )
    rough_prompt: str = Field(min_length=3, max_length=4000)
    business_question: str | None = Field(default=None, max_length=4000)
    workflow_mode: Literal["fast", "professional"] = "fast"
    revenue_reporting_currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    revenue_timezone: str | None = Field(default=None, max_length=100)

    @field_validator("revenue_reporting_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("revenue_timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Revenue timezone must be a valid IANA timezone such as Europe/Berlin") from exc
        return value


class CheckpointAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=8000)


# ── Helper functions ────────────────────────────────────────────────────────

def _model_sources(datasets: list[Dataset]) -> list[ModelSource]:
    return [
        ModelSource(
            dataset_id=str(item.id),
            filename=item.original_filename or Path(item.file_path).name,
            path=Path(item.file_path),
            sha256=item.sha256,
        )
        for item in datasets
    ]


def latest_open_checkpoint(db, session_id: str) -> dict | None:
    checkpoint = (
        db.query(Checkpoint)
        .filter(Checkpoint.session_id == session_id, Checkpoint.answer.is_(None))
        .order_by(Checkpoint.created_at.desc())
        .first()
    )
    if checkpoint is None:
        return None
    return {
        "stage": checkpoint.stage,
        "question": checkpoint.question,
        "pending_checkpoint_id": str(checkpoint.id),
    }


def session_payload(db, session: SessionModel, include_detail: bool = True) -> dict:
    payload = {
        "session_id": str(session.id),
        "status": session.status,
        "current_stage": session.current_stage,
        "workflow_mode": session.workflow_mode,
        "business_task": session.business_task,
        "error": session.error_message,
        "run_attempt": session.run_attempt or 0,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "checkpoint": (
            latest_open_checkpoint(db, str(session.id))
            if session.status == "paused_for_input"
            else None
        ),
    }
    if not include_detail:
        return payload

    checkpoints = (
        db.query(Checkpoint).filter(Checkpoint.session_id == session.id).all()
    )
    actions = (
        db.query(AgentAction).filter(AgentAction.session_id == session.id).all()
    )
    artifacts = (
        db.query(Artifact).filter(Artifact.session_id == session.id).all()
    )
    payload.update(
        {
            "result": session.result_summary,
            "checkpoints": [
                {"stage": item.stage, "question": item.question, "answer": item.answer}
                for item in checkpoints
            ],
            "actions": [
                {"stage": item.stage, "type": item.action_type} for item in actions
            ],
            "artifacts": [
                {
                    "id": str(item.id),
                    "type": item.type,
                    "url": f"/artifacts/{item.id}",
                    "title": (item.metadata_ or {}).get("title"),
                    "description": (item.metadata_ or {}).get("description"),
                    "format": (item.metadata_ or {}).get("format"),
                    "document_type": (item.metadata_ or {}).get("document_type"),
                    "evidence_id": (item.metadata_ or {}).get("evidence_id"),
                    "chart_type": (item.metadata_ or {}).get("chart_type"),
                    "subtitle": (item.metadata_ or {}).get("subtitle"),
                    "alt_text": (item.metadata_ or {}).get("alt_text"),
                }
                for item in artifacts
            ],
        }
    )
    return payload


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/sessions", status_code=status.HTTP_202_ACCEPTED)
def create_session(
    req: CreateSessionRequest,
    request: Request,
    guest: GuestPrincipal = Depends(require_guest_principal),
):
    db = SessionLocal()
    try:
        requested_ids = req.dataset_ids or ([req.dataset_id] if req.dataset_id else [])
        if not requested_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one dataset")
        if len(requested_ids) != len(set(requested_ids)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "A dataset cannot be selected more than once"
            )
        rows = (
            owned_dataset_query(db, guest)
            .filter(Dataset.id.in_(requested_ids))
            .with_for_update()
            .all()
        )
        by_id = {item.id: item for item in rows}
        if len(by_id) != len(requested_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more datasets were not found")
        datasets = [by_id[item] for item in requested_ids]
        if any(item.session_id is not None for item in datasets):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "One or more datasets are already assigned to an analysis",
            )

        session = SessionModel(
            user_id=uuid.uuid4(),
            status="queued",
            current_stage="ask",
            workflow_mode=req.workflow_mode,
            # Preserve a useful title even if the first graph checkpoint cannot
            # be written. AskAgent will replace this after human confirmation.
            business_task=req.business_question or req.rough_prompt,
        )
        db.add(session)
        db.flush()
        run_dir = settings.DATA_DIR / "runs" / str(session.id)
        joined_path, join_audit = materialize_data_model(
            _model_sources(datasets),
            [item.model_dump(mode="json") for item in req.joins],
            run_dir / "modelled-source.csv",
        )
        for dataset in datasets:
            dataset.session_id = session.id
        session_id = str(session.id)
        dataset_path = str(joined_path)
        original_filename = (
            datasets[0].original_filename
            if len(datasets) == 1
            else f"Approved model ({len(datasets)} sources)"
        )
        source_sha256 = (
            datasets[0].sha256
            if len(datasets) == 1
            else "Multiple source hashes recorded in source register"
        )
        source_register = [
            {
                "source_id": f"S{i}",
                "dataset_id": str(item.id),
                "filename": item.original_filename or Path(item.file_path).name,
                "format": Path(item.file_path).suffix.lower().lstrip(".").upper(),
                "sha256": item.sha256 or "Not recorded",
                "rows": item.row_count,
                "columns": (item.schema_profile or {}).get("column_count"),
                "grain": "One uploaded record per row; business grain requires human confirmation",
                "candidate_keys": [
                    name
                    for name, detail in (
                        (item.schema_profile or {}).get("columns") or {}
                    ).items()
                    if detail.get("null_count") == 0
                    and detail.get("unique_count") == item.row_count
                ],
                "licence": "Pending human ROCCC response",
            }
            for i, item in enumerate(datasets, 1)
        ]
        run_input = {
            "session_id": session_id,
            "file_path": dataset_path,
            "original_filename": original_filename,
            "source_sha256": source_sha256,
            "source_register": source_register,
            "join_audit": join_audit,
            "rough_prompt": req.rough_prompt,
            "business_question": req.business_question or req.rough_prompt,
            "analysis_objectives": req.analysis_objectives,
            "workflow_mode": req.workflow_mode,
            "revenue_reporting_currency": req.revenue_reporting_currency,
            "revenue_timezone": req.revenue_timezone,
        }
        # This envelope contains references and the user's analytical request,
        # never raw dataset rows, credentials, provider output, or API keys.
        session.run_input = run_input
        db.commit()
    except DataModelError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    finally:
        db.close()

    try:
        run_manager.submit_start(
            session_id,
            run_input,
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"session_id": session_id, "status": "queued"}


@router.get("/sessions")
def list_sessions(limit: int = 20):
    safe_limit = min(max(limit, 1), 100)
    db = SessionLocal()
    try:
        sessions = (
            db.query(SessionModel)
            .order_by(SessionModel.updated_at.desc())
            .limit(safe_limit)
            .all()
        )
        return {
            "sessions": [session_payload(db, item, include_detail=False) for item in sessions]
        }
    finally:
        db.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    db = SessionLocal()
    try:
        session = (
            db.query(SessionModel).filter(SessionModel.id == session_id).first()
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        return session_payload(db, session)
    finally:
        db.close()


@router.post("/sessions/{session_id}/resume", status_code=status.HTTP_202_ACCEPTED)
def resume_session(session_id: str, body: CheckpointAnswer):
    db = SessionLocal()
    try:
        session = (
            db.query(SessionModel).filter(SessionModel.id == session_id).first()
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        if session.status != "paused_for_input":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Session is not waiting for input"
            )
        open_checkpoint = (
            db.query(Checkpoint)
            .filter(Checkpoint.session_id == session.id, Checkpoint.answer.is_(None))
            .order_by(Checkpoint.created_at.desc())
            .first()
        )
        if open_checkpoint is not None:
            open_checkpoint.answer = body.answer
            open_checkpoint.resolved_at = func.now()
        session.status = "queued"
        session.error_message = None
        session.updated_at = func.now()
        db.commit()
    finally:
        db.close()
    try:
        run_manager.submit_resume(session_id, body.answer)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"session_id": session_id, "status": "queued"}


@router.post("/sessions/{session_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_session(session_id: str):
    db = SessionLocal()
    try:
        session = (
            db.query(SessionModel).filter(SessionModel.id == session_id).first()
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        if session.status != "error":
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Only failed sessions can be retried"
            )
        session.status = "queued"
        session.error_message = None
        session.updated_at = func.now()
        db.commit()
    finally:
        db.close()
    try:
        run_manager.submit_retry(session_id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"session_id": session_id, "status": "queued"}


# ── SSE progress stream ─────────────────────────────────────────────────────

async def _sse_generator(
    request: Request, session_id: str
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted messages until the client disconnects or session ends."""
    q = progress_bus.subscribe(session_id)
    # Send an initial heartbeat so the browser EventSource doesn't time out
    yield "data: {\"stage\":\"connected\",\"message\":\"Progress stream open\"}\n\n"
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("stage") == "done":
                    break
            except asyncio.TimeoutError:
                # Send a keepalive comment so the connection doesn't drop
                yield ": keepalive\n\n"
    finally:
        progress_bus.unsubscribe(session_id, q)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, request: Request):
    """Server-Sent Events stream for live stage progress.

    Connect with: `const es = new EventSource('/sessions/{id}/events')`
    Each event: `{ "stage": "analyze", "message": "Planning operations..." }`
    A final `{ "stage": "done" }` event signals completion.
    """
    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    finally:
        db.close()

    return StreamingResponse(
        _sse_generator(request, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
