"""Combine calculation accuracy with a source-aware browser journey gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).parents[3]
FRONTEND_ROOT = WORKSPACE_ROOT / "frontend"
BROWSER_REPORT = FRONTEND_ROOT / "e2e" / "reports" / "latest.json"


def frontend_fingerprint(root: Path = FRONTEND_ROOT) -> str:
    candidates = [root / "src", root / "package.json", root / "next.config.mjs", root / "playwright.config.mjs", root / "e2e" / "workspace.spec.mjs"]
    files: list[Path] = []
    for candidate in candidates:
        if candidate.is_dir():
            files.extend(item for item in candidate.rglob("*") if item.is_file() and item.suffix in {".js", ".mjs", ".css", ".json"})
        elif candidate.is_file():
            files.append(candidate)
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
        digest.update(item.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load_browser_gate(report_path: Path = BROWSER_REPORT, frontend_root: Path = FRONTEND_ROOT) -> dict[str, Any]:
    if not report_path.exists():
        return {"status": "not_run", "release_ready": False, "case_count": 0, "passed_count": 0, "failures": [], "message": "Browser journey tests have not been run."}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    current = frontend_fingerprint(frontend_root)
    if report.get("source_fingerprint") != current:
        return {**report, "status": "stale", "release_ready": False, "message": "Frontend code changed after the last browser journey run."}
    return report


def combine_release_status(analytical: dict[str, Any], browser: dict[str, Any]) -> dict[str, Any]:
    analytical_ready = bool(analytical.get("release_ready"))
    browser_ready = bool(browser.get("release_ready"))
    analytical_cases = int(analytical.get("case_count", 0))
    browser_cases = int(browser.get("case_count", 0))
    combined = dict(analytical)
    combined.update({
        "analytical_release_ready": analytical_ready,
        "browser_release_ready": browser_ready,
        "release_ready": analytical_ready and browser_ready,
        "case_count": analytical_cases + browser_cases,
        "passed_count": int(analytical.get("passed_count", 0)) + int(browser.get("passed_count", 0)),
        "failed_count": int(analytical.get("failed_count", 0)) + max(0, browser_cases - int(browser.get("passed_count", 0))),
        "category_scores": {**analytical.get("category_scores", {}), "browser_journey": 1.0 if browser_ready else 0.0},
        "browser_gate": browser,
    })
    return combined
