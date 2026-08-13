"""Evaluations router — run and retrieve the deterministic release gate."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from app.api.auth import require_api_key
from app.evals.runner import DEFAULT_REPORT_DIR, evaluate, write_reports
from app.evals.release_gate import combine_release_status, load_browser_gate
from app.evals.root_cause_runner import (
    DEFAULT_REPORT_DIR as ROOT_CAUSE_REPORT_DIR,
    combine_with_analytical_release,
    evaluate as evaluate_root_cause,
    write_reports as write_root_cause_reports,
)

router = APIRouter(tags=["evaluations"], dependencies=[Depends(require_api_key)])


@router.get("/evaluations/latest")
def latest_evaluation():
    report = DEFAULT_REPORT_DIR / "latest.json"
    if not report.exists():
        return {
            "status": "not_run",
            "message": "Run the accuracy evaluation to establish release readiness.",
        }
    payload = json.loads(report.read_text(encoding="utf-8"))
    root_cause_report = ROOT_CAUSE_REPORT_DIR / "latest.json"
    if root_cause_report.exists():
        root_cause_payload = json.loads(root_cause_report.read_text(encoding="utf-8"))
        payload["summary"] = combine_with_analytical_release(
            payload["summary"], root_cause_payload["summary"]
        )
        payload["root_cause_cases"] = root_cause_payload.get("cases", [])
    else:
        payload["summary"] = {
            **payload["summary"],
            "analytical_release_ready": bool(payload["summary"].get("release_ready")),
            "root_cause_release_ready": False,
            "release_ready": False,
            "root_cause_gate": {
                "status": "not_run",
                "release_ready": False,
                "message": "Run the controlled root-cause evaluation suite.",
            },
        }
    payload["summary"] = combine_release_status(payload["summary"], load_browser_gate())
    return payload


@router.post("/evaluations/run")
def run_evaluation():
    summary, results = evaluate()
    json_path, html_path = write_reports(summary, results)
    root_cause_summary, root_cause_results = evaluate_root_cause()
    root_json_path, root_html_path = write_root_cause_reports(
        root_cause_summary, root_cause_results
    )
    combined_summary = combine_with_analytical_release(summary, root_cause_summary)
    browser_gate = load_browser_gate()
    return {
        "status": "complete",
        "summary": combine_release_status(combined_summary, browser_gate),
        "browser_gate": browser_gate,
        "cases": [
            {
                "case_id": item.case_id,
                "name": item.name,
                "category": item.category,
                "severity": item.severity,
                "passed": item.passed,
            }
            for item in results
        ] + [
            {
                "case_id": item.case_id,
                "name": item.name,
                "category": "root_cause",
                "severity": item.severity,
                "passed": item.passed,
            }
            for item in root_cause_results
        ],
        "report_files": {
            "analytics_json": str(json_path),
            "analytics_html": str(html_path),
            "root_cause_json": str(root_json_path),
            "root_cause_html": str(root_html_path),
        },
    }
