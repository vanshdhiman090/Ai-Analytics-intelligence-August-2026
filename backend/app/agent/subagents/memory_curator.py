"""Governed experience-memory specialist.

This role never writes prompts or changes model behaviour.  It is a narrow
adapter around the deterministic memory store so the chief manager has one
auditable place for recall, failure fingerprinting, and verified recovery.
"""

from __future__ import annotations

from typing import Any

from app.agent.subagents.base import BaseSubAgent
from app.services.learning_memory import LearningMemoryStore


class MemoryCuratorSpecialist(BaseSubAgent):
    name = "MemoryCuratorSpecialist"
    domain_role = "Governed Experience Memory Curator"
    description = "Retrieves active lessons and records sanitized failures and verified recoveries."

    def __init__(self, store: LearningMemoryStore) -> None:
        self.store = store

    def recall(self, specialist: str, stage: str) -> list[Any]:
        return self.store.recall(specialist, stage)

    def record_failure(self, **payload: Any) -> str:
        return self.store.record_failure(**payload)

    def record_recovery(self, **payload: Any) -> None:
        self.store.record_recovery(**payload)

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "recall")
        specialist = str(kwargs.get("specialist") or "")
        stage = str(kwargs.get("stage") or "")
        if action != "recall":
            raise ValueError("Memory curator execute supports recall only; writes require verified manager events")
        lessons = self.recall(specialist, stage)
        return {
            "memory_review": {
                "specialist": specialist,
                "stage": stage,
                "active_lesson_count": len(lessons),
                "policy": "advisory_only",
            }
        }
