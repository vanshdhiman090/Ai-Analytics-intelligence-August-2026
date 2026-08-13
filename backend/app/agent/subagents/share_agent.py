"""ShareAgent — Visualization & Presentation Narrative Specialist."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.share_node import share_node
from app.agent.subagents.base import BaseSubAgent
from app.services.progress import emit_sync

logger = logging.getLogger(__name__)


class ShareAgent(BaseSubAgent):
    name = "ShareAgent"
    domain_role = "Visualization & Presentation Narrative Specialist"
    description = "Renders high-contrast chart visuals directly from validated evidence."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        emit_sync(state["session_id"], "share", "[ShareAgent] Generating high-contrast charts and visual evidence…")
        return share_node(state)
