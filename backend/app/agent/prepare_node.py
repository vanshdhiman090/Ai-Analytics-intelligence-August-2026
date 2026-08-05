"""
Milestone 1 — Prepare node, wired to the real database.

This ports the exact profiling logic already proven against Nike_Dataset.csv,
but now:
- writes the schema_profile to the real `datasets` table
- writes each checkpoint question to the real `checkpoints` table
- actually interrupts (pause/resume) instead of just returning a list
- logs the profiling step itself to `agent_actions` (the audit trail)
"""

import pandas as pd
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

from app.core.database import SessionLocal
from app.models.schema import Dataset, Checkpoint, AgentAction


class PrepareState(TypedDict):
    session_id: str
    file_path: str
    schema_profile: dict
    pending_checkpoint_id: str
    roccc_answers: dict


def profile_dataset(filepath: str) -> dict:
    """Same logic proven in prepare_stage.py, unchanged."""
    df = pd.read_csv(filepath)
    profile = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": {},
        "data_quality_flags": [],
    }
    for col in df.columns:
        col_data = df[col]
        col_profile = {
            "dtype_detected": str(col_data.dtype),
            "null_pct": round(float(col_data.isnull().mean() * 100), 2),
            "unique_count": int(col_data.nunique()),
        }
        if not pd.api.types.is_numeric_dtype(col_data):
            col_profile["likely_type"] = "categorical/text"
        else:
            col_profile["likely_type"] = "numeric"
            col_profile["mean"] = round(float(col_data.mean()), 2)
        profile["columns"][col] = col_profile

    dupes = df.duplicated().sum()
    profile["data_quality_flags"].append(
        f"{dupes} duplicate rows" if dupes else "No duplicates found"
    )
    return profile


def profile_and_log_node(state: PrepareState) -> PrepareState:
    """Runs exactly once. All side-effecting DB writes live here, before any
    interrupt — so they never get re-executed on resume."""
    db = SessionLocal()
    try:
        profile = profile_dataset(state["file_path"])

        dataset_row = Dataset(
            session_id=state["session_id"],
            file_path=state["file_path"],
            schema_profile=profile,
            row_count=profile["row_count"],
        )
        db.add(dataset_row)

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="prepare",
            action_type="schema_profiling",
            input_summary=f"Profiled {state['file_path']}",
            output_summary=f"{profile['row_count']} rows, {profile['column_count']} columns, "
                            f"flags: {profile['data_quality_flags']}",
        ))

        checkpoint_row = Checkpoint(
            session_id=state["session_id"],
            stage="prepare",
            question="Where did this dataset come from, and is it licensed/credible (ROCCC)?",
        )
        db.add(checkpoint_row)
        db.commit()

        return {"schema_profile": profile, "pending_checkpoint_id": str(checkpoint_row.id)}
    finally:
        db.close()


def ask_checkpoint_node(state: PrepareState) -> PrepareState:
    """interrupt() is the FIRST action here — nothing before it to duplicate
    when this node re-executes on resume."""
    answer = interrupt({
        "question": "Where did this dataset come from, and is it licensed/credible (ROCCC)?",
        "stage": "prepare",
        "pending_checkpoint_id": state["pending_checkpoint_id"],
    })

    db = SessionLocal()
    try:
        checkpoint_row = db.query(Checkpoint).filter(Checkpoint.id == state["pending_checkpoint_id"]).first()
        checkpoint_row.answer = answer
        db.commit()
        return {"roccc_answers": {"source_license": answer}}
    finally:
        db.close()


graph = StateGraph(PrepareState)
graph.add_node("profile_and_log", profile_and_log_node)
graph.add_node("ask_checkpoint", ask_checkpoint_node)
graph.set_entry_point("profile_and_log")
graph.add_edge("profile_and_log", "ask_checkpoint")
graph.add_edge("ask_checkpoint", END)

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)
