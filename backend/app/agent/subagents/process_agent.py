"""ProcessAgent — Data Audit & Cleaning Specialist."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.subagents.base import BaseSubAgent
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.schema import AgentAction
from app.services.progress import emit_sync
from app.services.run_state import mark_stage
from app.services.tabular import process_dataset

logger = logging.getLogger(__name__)


class ProcessAgent(BaseSubAgent):
    name = "ProcessAgent"
    domain_role = "Data Audit & Cleaning Specialist"
    description = "Executes conservative data cleaning, whitespace normalization, and join audit verification."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        mark_stage(state["session_id"], "process")
        emit_sync(state["session_id"], "process", "[ProcessAgent] Cleaning dataset and validating join cardinalities…")
        output_path = settings.DATA_DIR / "runs" / state["session_id"] / "cleaned.csv"
        result = process_dataset(state["file_path"], output_path)

        db = SessionLocal()
        try:
            db.add(
                AgentAction(
                    session_id=state["session_id"],
                    stage="process",
                    action_type="conservative_data_cleaning",
                    input_summary=f"{result.summary['rows_before']} rows from the uploaded dataset",
                    output_summary=(
                        f"{result.summary['rows_after']} rows retained; "
                        f"{len(result.findings)} quality findings; {len(result.integrity_checks)} integrity checks; "
                        f"transformations: {result.checklist['transformations']}"
                    ),
                    code_executed="Exact duplicate removal and string whitespace normalization only",
                )
            )
            db.commit()
        finally:
            db.close()

        join_checks = [
            {
                "check_id": f"JOIN{index}",
                "check": f"Approved join {item['left_key']} → {item['right_key']}",
                "status": "Pass" if item.get("row_multiplier") == 1 else "Warning",
                "detail": f"{item['rows_before']} rows before, {item['rows_after']} after; {item['unmatched_rows']} unmatched left rows",
                "implication": "Join cardinality was validated; any intentional grain expansion and unmatched left records remain visible.",
            }
            for index, item in enumerate(state.get("join_audit", []), 1)
        ]
        return {
            "cleaned_path": str(result.cleaned_path),
            "cleaning_checklist": result.checklist,
            "cleaning_log": result.cleaning_log,
            "integrity_checks": join_checks + result.integrity_checks,
            "validation_status": result.validation_status,
            "quality_findings": result.findings,
            "final_summary": result.summary,
        }
