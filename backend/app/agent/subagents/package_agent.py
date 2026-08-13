"""PackageAgent — Deliverable Assembly Specialist."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.package_node import package_node
from app.agent.subagents.base import BaseSubAgent
from app.services.progress import emit_sync

logger = logging.getLogger(__name__)


class PackageAgent(BaseSubAgent):
    name = "PackageAgent"
    domain_role = "Deliverable Assembly Specialist"
    description = "Assembles reproducible project ZIPs, Word docs, PDF reports, and editable PowerPoint presentation decks."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        emit_sync(state["session_id"], "package", "[PackageAgent] Assembling decision package, PowerPoint deck, and export files…")
        return package_node(state)
