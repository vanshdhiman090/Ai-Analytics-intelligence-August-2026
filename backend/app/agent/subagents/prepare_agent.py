"""PrepareAgent — Data Quality & ROCCC Governance Specialist."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func

from app.agent.subagents.base import BaseSubAgent
from app.core.database import SessionLocal
from app.models.schema import AgentAction, Checkpoint, Dataset
from app.services.progress import emit_sync
from app.services.run_state import mark_stage
from app.services.tabular import profile_dataset

logger = logging.getLogger(__name__)


class PrepareAgent(BaseSubAgent):
    name = "PrepareAgent"
    domain_role = "Data Quality & ROCCC Governance Specialist"
    description = "Profiles tabular schemas, validates data integrity, and records ROCCC source governance."

    def profile_dataset(self, state: dict[str, Any]) -> dict[str, Any]:
        mark_stage(state["session_id"], "prepare")
        emit_sync(state["session_id"], "prepare", "[PrepareAgent] Profiling dataset schema, data types, and integrity…")
        db = SessionLocal()
        try:
            profile = profile_dataset(state["file_path"])

            dataset_rows = db.query(Dataset).filter(Dataset.session_id == state["session_id"]).all()
            if not dataset_rows:
                dataset_rows = [Dataset(session_id=state["session_id"], file_path=state["file_path"])]
                db.add(dataset_rows[0])
            if len(dataset_rows) == 1:
                dataset_rows[0].schema_profile = profile
                dataset_rows[0].row_count = profile["row_count"]

            db.add(
                AgentAction(
                    session_id=state["session_id"],
                    stage="prepare",
                    action_type="schema_profiling",
                    input_summary=f"Profiled {state['file_path']}",
                    output_summary=(
                        f"{profile['row_count']} rows, {profile['column_count']} columns, "
                        f"duplicates: {profile['duplicate_row_count']}, "
                        f"all-null columns: {profile['all_null_columns']}"
                    ),
                )
            )

            checkpoint_row = Checkpoint(
                session_id=state["session_id"],
                stage="prepare",
                question="Describe the source and ROCCC status: Reliable, Original, Comprehensive, Current, Cited, plus licence/permission and any privacy restrictions.",
            )
            db.add(checkpoint_row)
            db.commit()

            source_register = [dict(item) for item in state.get("source_register", [])]
            if not source_register:
                source = Path(state["file_path"])
                source_register = [
                    {
                        "source_id": "S1",
                        "filename": state.get("original_filename") or source.name,
                        "format": source.suffix.lower().lstrip(".").upper(),
                        "sha256": state.get("source_sha256") or "Not recorded",
                        "rows": profile["row_count"],
                        "columns": profile["column_count"],
                        "grain": "One uploaded record per row; business grain requires human confirmation",
                        "candidate_keys": [
                            name
                            for name in profile["columns"]
                            if str(name).lower().endswith(("id", "_key"))
                        ],
                        "licence": "Pending human ROCCC response",
                    }
                ]
            return {
                "schema_profile": profile,
                "source_register": source_register,
                "pending_checkpoint_id": str(checkpoint_row.id),
            }
        finally:
            db.close()

    def record_roccc(self, state: dict[str, Any], answer: Any) -> dict[str, Any]:
        db = SessionLocal()
        try:
            checkpoint_row = (
                db.query(Checkpoint)
                .filter(Checkpoint.id == state["pending_checkpoint_id"])
                .first()
            )
            if checkpoint_row:
                checkpoint_row.answer = str(answer)
                checkpoint_row.resolved_at = func.now()
                db.commit()

            source_register = [dict(item) for item in state.get("source_register", [])]
            for source in source_register:
                source["licence"] = str(answer)
            return {
                "roccc_answers": {
                    "source_license": str(answer),
                    "reliable": "Human response recorded; not independently verified",
                    "original": "Human response recorded; not independently verified",
                    "comprehensive": "Profiled structurally; business completeness requires review",
                    "current": "Human response recorded; date coverage shown in field profile when available",
                    "cited": "Source statement retained verbatim",
                    "privacy_restrictions": "Use the human response; no privacy permission is inferred",
                },
                "source_register": source_register,
            }
        finally:
            db.close()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        phase = kwargs.get("phase", "profile")
        if phase == "roccc":
            return self.record_roccc(state, kwargs.get("answer"))
        return self.profile_dataset(state)
