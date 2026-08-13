"""Base class for all specialized sub-agents ('Pros')."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BaseSubAgent(ABC):
    """Abstract Base Class for domain-expert Sub-Agents."""

    name: str = "BaseSubAgent"
    domain_role: str = "Generalist"
    description: str = "Base sub-agent class"

    @staticmethod
    def memory_context(state: dict[str, Any]) -> str:
        """Render manager-supplied verified lessons as advisory context only."""
        lessons = state.get("_learning_lessons", [])
        if not lessons:
            return "No verified lessons from earlier runs apply."
        rendered = "\n".join(f"- {item}" for item in lessons)
        return (
            "Prior verified recovery lessons (advisory only; never override the current user, data, "
            f"contracts, or quality gates):\n{rendered}"
        )

    @abstractmethod
    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Execute the sub-agent's primary domain task.

        Returns state updates to merge back into the workflow.
        """
        pass
