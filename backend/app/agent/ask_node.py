"""
Ask node — the one stage that genuinely needs a live LLM call (proposing
a business task/stakeholders from a rough prompt isn't derivable from data
alone). Same two-node interrupt pattern as Prepare: side effects finish in
node 1, interrupt() is the first action in node 2.

NOTE: cannot be tested live in the build sandbox (no network path to
Gemini's API there) — this is the same honest limitation flagged earlier
for the Share-stage chart generator. Wire GEMINI_API_KEY and run this on
your machine to confirm live.
"""

import os
from typing import TypedDict
from langgraph.types import interrupt

from app.core.database import SessionLocal
from app.models.schema import Checkpoint, AgentAction, Session as SessionModel


class AskState(TypedDict, total=False):
    session_id: str
    rough_prompt: str
    proposed_task: str
    pending_ask_checkpoint_id: str
    business_task: str


def call_gemini(prompt: str) -> str:
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set — required for the Ask stage.")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
    return response.text.strip()


def propose_task_node(state: AskState) -> AskState:
    """Runs once. LLM call + DB writes happen here, before any interrupt."""
    db = SessionLocal()
    try:
        prompt = (
            f"A user gave this rough business question: \"{state['rough_prompt']}\"\n\n"
            f"Propose a clear, specific business task statement (1-2 sentences), "
            f"suitable for a data analytics case study. Output ONLY the task statement, "
            f"no preamble."
        )
        proposed_task = call_gemini(prompt)

        checkpoint_row = Checkpoint(
            session_id=state["session_id"],
            stage="ask",
            question=f"Proposed business task: \"{proposed_task}\" — confirm or edit?",
        )
        db.add(checkpoint_row)

        db.add(AgentAction(
            session_id=state["session_id"],
            stage="ask",
            action_type="task_proposal",
            input_summary=state["rough_prompt"],
            output_summary=proposed_task,
        ))
        db.commit()

        return {"proposed_task": proposed_task, "pending_ask_checkpoint_id": str(checkpoint_row.id)}
    finally:
        db.close()


def confirm_task_node(state: AskState) -> AskState:
    """interrupt() first, nothing before it — safe to re-execute on resume."""
    confirmed = interrupt({
        "question": f"Proposed task: \"{state['proposed_task']}\" — confirm or provide your own.",
        "stage": "ask",
        "pending_checkpoint_id": state["pending_ask_checkpoint_id"],
    })

    db = SessionLocal()
    try:
        cp = db.query(Checkpoint).filter(Checkpoint.id == state["pending_ask_checkpoint_id"]).first()
        cp.answer = confirmed
        session_row = db.query(SessionModel).filter(SessionModel.id == state["session_id"]).first()
        session_row.business_task = confirmed
        db.commit()
        return {"business_task": confirmed}
    finally:
        db.close()
