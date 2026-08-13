"""
Prepare phase, wired to the real database with dataset-aware profiling:
- writes the schema_profile to the real `datasets` table
- writes each checkpoint question to the real `checkpoints` table
- actually interrupts (pause/resume) instead of just returning a list
- logs the profiling step itself to `agent_actions` (the audit trail)
"""

from pathlib import Path
from typing import TypedDict
from langgraph.types import interrupt
from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.schema import Dataset, Checkpoint, AgentAction
from app.services.tabular import profile_dataset
from app.services.run_state import mark_stage
from app.services.progress import emit_sync


class PrepareState(TypedDict):
    session_id: str
    file_path: str
    original_filename: str
    source_sha256: str
    schema_profile: dict
    pending_checkpoint_id: str
    roccc_answers: dict
    source_register: list
    join_audit: list


def profile_and_log_node(state: PrepareState) -> PrepareState:
    """Runs exactly once. All side-effecting DB writes live here, before any
    interrupt — so they never get re-executed on resume."""
    mark_stage(state["session_id"], "prepare")
    emit_sync(state["session_id"], "prepare", "Profiling dataset structure, types, and quality…")
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

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="prepare",
            action_type="schema_profiling",
            input_summary=f"Profiled {state['file_path']}",
            output_summary=f"{profile['row_count']} rows, {profile['column_count']} columns, "
                            f"duplicates: {profile['duplicate_row_count']}, "
                            f"all-null columns: {profile['all_null_columns']}",
        ))

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
            source_register = [{
                "source_id": "S1", "filename": state.get("original_filename") or source.name,
                "format": source.suffix.lower().lstrip(".").upper(), "sha256": state.get("source_sha256") or "Not recorded",
                "rows": profile["row_count"], "columns": profile["column_count"],
                "grain": "One uploaded record per row; business grain requires human confirmation",
                "candidate_keys": [name for name in profile["columns"] if str(name).lower().endswith(("id", "_key"))],
                "licence": "Pending human ROCCC response",
            }]
        return {"schema_profile": profile, "source_register": source_register, "pending_checkpoint_id": str(checkpoint_row.id)}
    finally:
        db.close()


def ask_checkpoint_node(state: PrepareState) -> PrepareState:
    """interrupt() is the FIRST action here — nothing before it to duplicate
    when this node re-executes on resume."""
    answer = interrupt({
        "question": "Describe the source and ROCCC status: Reliable, Original, Comprehensive, Current, Cited, plus licence/permission and any privacy restrictions.",
        "stage": "prepare",
        "pending_checkpoint_id": state["pending_checkpoint_id"],
    })

    db = SessionLocal()
    try:
        checkpoint_row = db.query(Checkpoint).filter(Checkpoint.id == state["pending_checkpoint_id"]).first()
        checkpoint_row.answer = answer
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


