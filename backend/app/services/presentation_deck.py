"""Create an editable native PowerPoint from validated analysis state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from app.domain.contracts import ActionPackage


SERVICE_DIR = Path(__file__).resolve().parent
DECK_SCRIPT = SERVICE_DIR / "presentation_deck.mjs"


def _first_existing(candidates: list[Path]) -> Path | None:
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _node_binary() -> Path:
    configured = os.getenv("PRESENTATION_NODE_BINARY")
    candidates = [Path(configured)] if configured else []
    candidates.extend(
        [
            Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
            Path(shutil.which("node") or ""),
        ]
    )
    resolved = _first_existing(candidates)
    if resolved is None:
        raise RuntimeError("Editable PowerPoint generation requires Node.js. Set PRESENTATION_NODE_BINARY.")
    return resolved


def _artifact_tool_entry() -> Path:
    configured = os.getenv("ARTIFACT_TOOL_ENTRY")
    candidates = [Path(configured)] if configured else []
    candidates.append(
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
        / "@oai"
        / "artifact-tool"
        / "dist"
        / "artifact_tool.mjs"
    )
    resolved = _first_existing(candidates)
    if resolved is None:
        raise RuntimeError("Editable PowerPoint generation requires @oai/artifact-tool. Set ARTIFACT_TOOL_ENTRY.")
    return resolved


def presentation_runtime_available() -> bool:
    try:
        _node_binary()
        _artifact_tool_entry()
    except RuntimeError:
        return False
    return True


def create_stakeholder_pptx(state: Mapping[str, Any], package: ActionPackage, artifact_dir: Path) -> Path:
    """Generate one editable stakeholder-ready .pptx artifact."""
    payload = {
        "session_id": state.get("session_id"),
        "business_question": state.get("business_question"),
        "analysis_summary": state.get("analysis_summary"),
        "analysis_brief": state.get("analysis_brief") or {},
        "schema_profile": state.get("schema_profile") or {},
        "source_register": state.get("source_register") or [],
        "roccc_answers": state.get("roccc_answers") or {},
        "validation_status": state.get("validation_status") or "Unknown",
        "evidence": state.get("evidence") or [],
        "findings": state.get("findings") or [],
        "recommendations": [item.model_dump(mode="json") for item in package.recommendations],
        "limitations": package.limitations,
        "monitoring_metrics": package.monitoring_metrics,
        "original_filename": state.get("original_filename") or "Uploaded dataset",
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    destination = artifact_dir / "deck.pptx"
    with tempfile.TemporaryDirectory(prefix="analytics-deck-") as staging:
        staging_dir = Path(staging)
        input_path = staging_dir / "deck-input.json"
        staged_output = staging_dir / "deck.pptx"
        input_path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        completed = subprocess.run(
            [str(_node_binary()), str(DECK_SCRIPT), str(input_path), str(staged_output), str(_artifact_tool_entry())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        if completed.returncode != 0 or not staged_output.is_file():
            detail = (completed.stderr or completed.stdout or "Unknown presentation export error").strip()
            raise RuntimeError(f"Editable PowerPoint generation failed: {detail[-2000:]}")
        shutil.copy2(staged_output, destination)
    return destination

