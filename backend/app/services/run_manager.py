"""Bounded in-process execution with durable LangGraph recovery semantics.

This is intentionally small: it prevents HTTP timeouts today while keeping the
state in PostgreSQL. A distributed queue can replace this class without
changing the API contract when the product is deployed at scale.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any, Literal, Mapping

from langgraph.errors import EmptyInputError
from langgraph.types import Command
from sqlalchemy import func

from app.agent.orchestrator import app as pipeline
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import Checkpoint, Session as SessionModel
from app.services.progress import emit_sync

logger = logging.getLogger(__name__)
RunMode = Literal["start", "resume", "retry"]


class RecoveryInputMissingError(RuntimeError):
    """The run has neither a durable graph checkpoint nor its original input."""


def invoke_pipeline(
    graph: Any,
    mode: RunMode,
    payload: Any,
    config: dict[str, Any],
    recovery_input: Mapping[str, Any] | None = None,
) -> tuple[dict, bool]:
    """Invoke a graph and safely recover a retry that has no first checkpoint.

    Returns ``(result, restarted_from_input)``. A retry first asks LangGraph to
    continue its durable checkpoint. Only LangGraph's explicit EmptyInputError
    permits a clean restart from the persisted start envelope; all other
    failures remain failures and are never hidden by a duplicate restart.
    """
    if mode == "start":
        return graph.invoke(payload, config=config), False
    if mode == "resume":
        return graph.invoke(Command(resume=payload), config=config), False
    try:
        return graph.invoke(None, config=config), False
    except EmptyInputError as exc:
        if not recovery_input:
            raise RecoveryInputMissingError(
                "This analysis failed before its first recovery checkpoint and its original start input "
                "is unavailable. Start a new analysis instead of retrying this legacy session."
            ) from exc
        return graph.invoke(dict(recovery_input), config=config), True


def derive_run_outcome(result: dict) -> tuple[str, str]:
    """Convert a LangGraph result into the durable API lifecycle state."""
    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return "complete", "complete"
    checkpoint = interrupts[0].value or {}
    return "paused_for_input", checkpoint.get("stage", "ask")


def safe_error_message(exc: Exception) -> str:
    """Persist a useful error without allowing unbounded provider output."""
    return f"{type(exc).__name__}: {str(exc)}"[:1000]


class RunManager:
    def __init__(self, max_workers: int):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analysis-run")
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def _submit(self, session_id: str, mode: RunMode, payload: Any = None) -> None:
        with self._lock:
            existing = self._futures.get(session_id)
            if existing is not None and not existing.done():
                raise RuntimeError("This analysis is already running")
            future = self._executor.submit(self._execute, session_id, mode, payload)
            self._futures[session_id] = future
            future.add_done_callback(lambda _: self._forget(session_id))

    def submit_start(self, session_id: str, payload: dict) -> None:
        self._submit(session_id, "start", payload)

    def submit_resume(self, session_id: str, answer: str) -> None:
        self._submit(session_id, "resume", answer)

    def submit_retry(self, session_id: str) -> None:
        self._submit(session_id, "retry")

    def _forget(self, session_id: str) -> None:
        with self._lock:
            self._futures.pop(session_id, None)

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            future = self._futures.get(session_id)
            return future is not None and not future.done()

    def _execute(self, session_id: str, mode: RunMode, payload: Any) -> None:
        self._mark_started(session_id)
        config = {"configurable": {"thread_id": session_id}}
        try:
            recovery_input = self._load_run_input(session_id) if mode == "retry" else None
            result, restarted = invoke_pipeline(
                pipeline, mode, payload, config, recovery_input=recovery_input
            )
            if restarted:
                emit_sync(
                    session_id,
                    "ask",
                    "No recovery checkpoint existed, so the Manager safely restarted from the saved request.",
                )
            self._mark_result(session_id, result)
        except Exception as exc:  # the error is persisted; the worker must not die silently
            logger.exception("Analysis session %s failed", session_id)
            self._mark_failed(session_id, exc)

    @staticmethod
    def _load_run_input(session_id: str) -> dict[str, Any] | None:
        db = SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if session is None or not isinstance(session.run_input, dict):
                return None
            return dict(session.run_input)
        finally:
            db.close()

    @staticmethod
    def _mark_started(session_id: str) -> None:
        db = SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if session is None:
                return
            session.status = "running"
            session.error_message = None
            session.run_attempt = (session.run_attempt or 0) + 1
            session.started_at = func.now()
            session.completed_at = None
            session.updated_at = func.now()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _mark_result(session_id: str, result: dict) -> None:
        status, stage = derive_run_outcome(result)
        db = SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if session is None:
                return
            session.status = status
            session.current_stage = stage
            if status == "complete":
                session.completed_at = func.now()
                emit_sync(session_id, "done", "Analysis complete.")
            elif status == "paused_for_input":
                interrupt_value = (result.get("__interrupt__") or [])[0].value or {}
                existing = db.query(Checkpoint).filter(
                    Checkpoint.session_id == session_id,
                    Checkpoint.stage == stage,
                    Checkpoint.answer.is_(None),
                ).first()
                if existing is None:
                    db.add(Checkpoint(session_id=session_id, stage=stage, question=str(interrupt_value.get("question") or "Input required")))
                emit_sync(session_id, "done", "Waiting for your input…")
            session.updated_at = func.now()
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _mark_failed(session_id: str, exc: Exception) -> None:
        message = safe_error_message(exc)
        db = SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            if session is None:
                return
            session.status = "error"
            session.error_message = message
            session.updated_at = func.now()
            db.commit()
            emit_sync(session_id, "done", f"Analysis stopped: {message[:120]}")
        finally:
            db.close()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


run_manager = RunManager(settings.RUN_WORKERS)
