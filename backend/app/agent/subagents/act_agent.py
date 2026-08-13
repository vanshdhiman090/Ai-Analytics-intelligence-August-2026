"""ActAgent — Strategic Recommendation Specialist."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.act_node import act_node
from app.agent.subagents.base import BaseSubAgent
from app.services.progress import emit_sync

logger = logging.getLogger(__name__)


class ActAgent(BaseSubAgent):
    name = "ActAgent"
    domain_role = "Strategic Recommendation Specialist"
    description = "Derives conservative evidence-linked recommendations, limitations, and monitoring KPIs."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        emit_sync(state["session_id"], "act", "[ActAgent] Formulating conservative recommendations & risk limitations…")
        return act_node(state)
