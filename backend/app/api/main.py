"""
API layer — exposes the LangGraph pipeline over HTTP. Thin by design: this
layer's only job is to relay requests to the orchestrator and expose state,
per the architecture decision in the master plan (Section 6). All real
logic stays in the agent nodes.
"""

import sys
sys.path.insert(0, "/home/claude/ai-analytics-workspace/backend")

import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.types import Command

from app.core.database import SessionLocal
from app.models.schema import Session as SessionModel, Checkpoint, AgentAction, Artifact
from app.agent.orchestrator import app as pipeline

app = FastAPI(title="AI Analytics Workspace API")


class CreateSessionRequest(BaseModel):
    file_path: str
    rough_prompt: str
    business_question: str


class CheckpointAnswer(BaseModel):
    answer: str


@app.post("/sessions")
def create_session(req: CreateSessionRequest):
    db = SessionLocal()
    try:
        session_row = SessionModel(user_id=uuid.uuid4(), status="active", current_stage="prepare")
        db.add(session_row)
        db.commit()
        session_id = str(session_row.id)

        config = {"configurable": {"thread_id": session_id}}
        result = pipeline.invoke(
            {"session_id": session_id, "file_path": req.file_path,
             "rough_prompt": req.rough_prompt, "business_question": req.business_question},
            config=config,
        )

        paused = result.get("__interrupt__") is not None
        session_row.status = "paused_for_input" if paused else "complete"
        db.commit()

        return {
            "session_id": session_id,
            "status": session_row.status,
            "checkpoint": result.get("__interrupt__")[0].value if paused else None,
        }
    finally:
        db.close()


@app.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, body: CheckpointAnswer):
    config = {"configurable": {"thread_id": session_id}}
    result = pipeline.invoke(Command(resume=body.answer), config=config)

    still_paused = result.get("__interrupt__") is not None

    db = SessionLocal()
    try:
        session_row = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session_row:
            raise HTTPException(404, "Session not found")

        session_row.status = "paused_for_input" if still_paused else "complete"
        session_row.current_stage = "complete" if not still_paused else session_row.current_stage
        db.commit()

        return {
            "session_id": session_id,
            "status": session_row.status,
            "checkpoint": result.get("__interrupt__")[0].value if still_paused else None,
            "findings_count": len(result.get("findings", [])) if not still_paused else None,
            "recommendations_count": len(result.get("recommendations", [])) if not still_paused else None,
        }
    finally:
        db.close()


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    db = SessionLocal()
    try:
        session_row = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if not session_row:
            raise HTTPException(404, "Session not found")
        checkpoints = db.query(Checkpoint).filter(Checkpoint.session_id == session_id).all()
        actions = db.query(AgentAction).filter(AgentAction.session_id == session_id).all()
        artifacts = db.query(Artifact).filter(Artifact.session_id == session_id).all()

        return {
            "session_id": session_id,
            "status": session_row.status,
            "current_stage": session_row.current_stage,
            "business_task": session_row.business_task,
            "checkpoints": [{"stage": c.stage, "question": c.question, "answer": c.answer} for c in checkpoints],
            "actions": [{"stage": a.stage, "type": a.action_type} for a in actions],
            "artifacts": [{"type": ar.type, "path": ar.file_path} for ar in artifacts],
        }
    finally:
        db.close()
