"""Persistent, bounded learning memory for specialist-agent recovery lessons."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.schema import AgentMemory


@dataclass(frozen=True)
class RecalledLesson:
    memory_id: str
    error_summary: str
    guidance: str
    success_count: int


def _bounded(value: object, limit: int = 500) -> str:
    text = " ".join(str(value).split())
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return text[:limit]


def sanitized_error_summary(error: Exception) -> str:
    return _bounded(f"{type(error).__name__}: {error}")


def error_signature(error: Exception) -> tuple[str, str]:
    """Create a stable signature without retaining a traceback or full input data."""
    summary = sanitized_error_summary(error)
    normalized = re.sub(r"\b\d+\b", "#", summary.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest(), summary


class LearningMemoryStore:
    """Stores failures as candidates and promotes them only after recovery succeeds."""

    def recall(self, specialist: str, stage: str, limit: int = 5) -> list[RecalledLesson]:
        db = SessionLocal()
        try:
            rows = (
                db.query(AgentMemory)
                .filter(
                    AgentMemory.specialist_name == specialist,
                    AgentMemory.stage == stage,
                    AgentMemory.scope_key == settings.MEMORY_SCOPE,
                    AgentMemory.status == "active",
                )
                .order_by(AgentMemory.success_count.desc(), AgentMemory.updated_at.desc())
                .limit(limit)
                .all()
            )
            return [RecalledLesson(str(row.id), row.error_summary, row.guidance, row.success_count) for row in rows]
        finally:
            db.close()

    def record_failure(self, *, session_id: str, manager: str, specialist: str, stage: str, error: Exception) -> str:
        fingerprint, summary = error_signature(error)
        db = SessionLocal()
        try:
            row = (
                db.query(AgentMemory)
                .filter(
                    AgentMemory.specialist_name == specialist,
                    AgentMemory.stage == stage,
                    AgentMemory.scope_key == settings.MEMORY_SCOPE,
                    AgentMemory.error_fingerprint == fingerprint,
                )
                .first()
            )
            if row is None:
                row = AgentMemory(
                    session_id=session_id,
                    scope_key=settings.MEMORY_SCOPE,
                    manager_name=manager,
                    specialist_name=specialist,
                    stage=stage,
                    error_fingerprint=fingerprint,
                    error_summary=summary,
                    guidance="Candidate lesson; it is not reused until a retry proves recovery.",
                    status="candidate",
                    occurrence_count=1,
                    success_count=0,
                )
                db.add(row)
            else:
                row.occurrence_count += 1
                row.error_summary = summary
                row.session_id = session_id
            db.commit()
            return fingerprint
        finally:
            db.close()

    def record_recovery(self, *, specialist: str, stage: str, fingerprint: str, attempt: int) -> None:
        db = SessionLocal()
        try:
            row = (
                db.query(AgentMemory)
                .filter(
                    AgentMemory.specialist_name == specialist,
                    AgentMemory.stage == stage,
                    AgentMemory.scope_key == settings.MEMORY_SCOPE,
                    AgentMemory.error_fingerprint == fingerprint,
                )
                .first()
            )
            if row is not None:
                row.status = "active"
                row.success_count += 1
                row.guidance = (
                    f"A retry succeeded on attempt {attempt}. Re-check the specialist input contract, reuse only "
                    "validated state, and treat this error as recoverable before escalating."
                )
                db.commit()
        finally:
            db.close()


def format_lessons(lessons: list[RecalledLesson]) -> str:
    if not lessons:
        return "No validated lessons from earlier runs apply."
    return "\n".join(f"- Previous issue: {item.error_summary}. Guidance: {item.guidance}" for item in lessons)


learning_memory = LearningMemoryStore()
