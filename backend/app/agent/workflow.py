"""User-controlled workflow and deliverable choices.

These are intentionally small, typed policy values: a prior lesson or an LLM
may never change a workflow gate or request an artifact on the user's behalf.
"""

from __future__ import annotations

import json
from typing import Any

WORKFLOW_MODES = {
    "fast": {
        "label": "Fast Analysis",
        "description": "A guided, validated analysis with one final choice of deliverable.",
        "approval_stages": (),
    },
    "professional": {
        "label": "Full Professional Workflow",
        "description": "The complete Ask, Prepare, Process and Analyze review workflow.",
        "approval_stages": ("ask", "prepare", "process", "analyze"),
    },
}

DELIVERABLES = {
    "executive_report": "Executive report",
    "professional_case_study": "Professional case-study report",
    "technical_report": "Technical analyst report",
    "presentation": "Editable PowerPoint presentation",
    "project_zip": "Reproducible project ZIP",
}


def mode_is_valid(mode: str) -> bool:
    return mode in WORKFLOW_MODES


def needs_approval(state: dict[str, Any], stage: str) -> bool:
    mode = str(state.get("workflow_mode") or "professional")
    return stage in WORKFLOW_MODES.get(mode, WORKFLOW_MODES["professional"])["approval_stages"]


def parse_deliverable_selection(answer: Any) -> dict[str, Any]:
    """Accept UI JSON or a plain-text answer without silently creating files."""
    raw = answer if isinstance(answer, dict) else {}
    if not raw and isinstance(answer, str):
        try:
            raw = json.loads(answer)
        except json.JSONDecodeError:
            raw = {"requested_outputs": []}
    requested = raw.get("requested_outputs", [])
    if not isinstance(requested, list):
        requested = []
    outputs = [item for item in requested if item in DELIVERABLES]
    return {
        "requested_outputs": list(dict.fromkeys(outputs)),
        "report_style": str(raw.get("report_style") or "executive"),
    }
