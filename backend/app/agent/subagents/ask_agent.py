"""AskAgent — Business Scope & Briefing Specialist."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

from app.agent.subagents.base import BaseSubAgent
from app.core.database import SessionLocal
from app.domain.contracts import AnalysisBrief
from app.models.schema import AgentAction, Checkpoint, Session as SessionModel
from app.services.llm import generate_structured
from app.services.progress import emit_sync
from app.services.run_state import mark_stage

logger = logging.getLogger(__name__)


def format_brief(brief: AnalysisBrief) -> str:
    stakeholders = "; ".join(
        f"{item.name} ({item.role}): {item.decision_interest}" for item in brief.stakeholders
    )
    return (
        f"Objective: {brief.objective}\n"
        f"Decision: {brief.decision}\n"
        f"Primary question: {brief.primary_question}\n"
        f"Stakeholders: {stakeholders}\n"
        f"Success criteria: {'; '.join(brief.success_criteria)}\n"
        f"Required context: {'; '.join(brief.required_context) or 'None identified'}"
    )


def resolve_business_task(answer: object, proposed_task: str) -> str:
    normalized = str(answer).strip().lower()
    confirmations = {"confirm", "confirmed", "yes", "approve", "approved"}
    return proposed_task if normalized in confirmations else str(answer).strip()


class AskAgent(BaseSubAgent):
    name = "AskAgent"
    domain_role = "Business Scope & Requirements Specialist"
    description = "Formulates rigorous business analysis briefs and confirms business questions."

    def propose_brief(self, state: dict[str, Any]) -> dict[str, Any]:
        mark_stage(state["session_id"], "ask")
        emit_sync(state["session_id"], "ask", "[AskAgent] Analyzing business goals & drafting analysis brief…")
        db = SessionLocal()
        try:
            prompt = (
                "Turn the user's rough request into a rigorous Google Data Analytics Ask-phase brief. "
                "Do not invent names, targets, deadlines, data definitions, or business facts. Mark unknown "
                "people as 'Unspecified' and put missing external facts in required_context. Success criteria "
                "must describe what the analysis must establish, not fabricated numeric targets.\n\n"
                f"User request:\n{state['rough_prompt']}\n\n"
                f"User-selected analytical objectives: {', '.join(state.get('analysis_objectives', [])) or 'No explicit selection'}. "
                "Use these as scope priorities without inventing unsupported methods or claims.\n\n"
                f"{self.memory_context(state)}"
            )
            brief = generate_structured(prompt, AnalysisBrief)
            proposed_task = brief.primary_question
            brief_text = format_brief(brief)

            checkpoint_row = Checkpoint(
                session_id=state["session_id"],
                stage="ask",
                question=f"Proposed analysis brief:\n{brief_text}\n\nConfirm or provide a revised primary question.",
            )
            db.add(checkpoint_row)
            db.add(
                AgentAction(
                    session_id=state["session_id"],
                    stage="ask",
                    action_type="analysis_brief_proposal",
                    input_summary=state["rough_prompt"],
                    output_summary=brief.model_dump_json(),
                )
            )
            db.commit()

            return {
                "proposed_task": proposed_task,
                "analysis_brief": brief.model_dump(mode="json"),
                "pending_ask_checkpoint_id": str(checkpoint_row.id),
            }
        finally:
            db.close()

    def confirm_brief(self, state: dict[str, Any], answer: Any) -> dict[str, Any]:
        business_task = resolve_business_task(answer, state["proposed_task"])
        db = SessionLocal()
        try:
            checkpoint = (
                db.query(Checkpoint)
                .filter(Checkpoint.id == state["pending_ask_checkpoint_id"])
                .first()
            )
            session = db.query(SessionModel).filter(SessionModel.id == state["session_id"]).first()
            if checkpoint is None or session is None:
                raise RuntimeError("The Ask checkpoint or session no longer exists.")
            checkpoint.answer = str(answer)
            checkpoint.resolved_at = func.now()
            session.business_task = business_task
            db.commit()
            return {"business_task": business_task, "business_question": business_task}
        finally:
            db.close()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        phase = kwargs.get("phase", "propose")
        if phase == "confirm":
            return self.confirm_brief(state, kwargs.get("answer"))
        return self.propose_brief(state)
