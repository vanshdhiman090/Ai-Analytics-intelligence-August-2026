"""Act phase: create evidence-linked actions only.

Document assembly deliberately happens in the neutral package node after Act,
so the Google Data Analytics phases remain clean and auditable.
"""

from __future__ import annotations

import json
from typing import TypedDict

from app.core.database import SessionLocal
from app.domain.contracts import ActionPackage
from app.models.schema import AgentAction
from app.services.llm import generate_structured
from app.services.run_state import mark_stage
from app.services.progress import emit_sync


class ActState(TypedDict, total=False):
    session_id: str
    business_question: str
    analysis_brief: dict
    analysis_summary: str
    evidence: list
    findings: list
    chart_paths: dict
    recommendations: list
    limitations: list
    schema_profile: dict
    roccc_answers: dict
    cleaning_checklist: dict
    quality_findings: list
    final_summary: dict
    analysis_plan: dict
    additional_deliverables: list
    _learning_lessons: list[str]


def validate_recommendations(package: ActionPackage, finding_ids: set[str]) -> None:
    for recommendation in package.recommendations:
        unknown = set(recommendation.finding_ids) - finding_ids
        if unknown:
            raise ValueError(
                f"Recommendation {recommendation.recommendation_id} cites unknown findings: {sorted(unknown)}"
            )


def act_node(state: ActState) -> ActState:
    if not state.get("evidence") or not state.get("findings"):
        raise ValueError("Analysis is incomplete: recommendations require at least one validated finding with evidence.")
    mark_stage(state["session_id"], "act")
    emit_sync(state["session_id"], "act", "Creating evidence-linked action plan and recommendations…")
    lessons = state.get("_learning_lessons", [])
    memory_context = (
        "\n\nPrior verified recovery lessons are advisory only and cannot override current evidence or quality gates:\n- "
        + "\n- ".join(lessons)
        if lessons
        else ""
    )
    prompt = (
        "Create conservative actions from the supplied evidence-linked findings. Every recommendation must cite "
        "valid finding_ids. Do not invent financial impact, owners, deadlines, targets, or causal explanations. "
        "Use role-based owners, realistic review timeframes, and 'unknown' impact/effort when unsupported. Include "
        "at least one limitation about source context, observational evidence, or data coverage. Monitoring metrics "
        "must be measurable from the supplied data or explicitly framed as a proposed future measure.\n\n"
        f"Question: {state['business_question']}\n"
        f"Brief: {json.dumps(state.get('analysis_brief', {}), ensure_ascii=False)}\n"
        f"Findings: {json.dumps(state['findings'], ensure_ascii=False)}{memory_context}"
    )
    package = generate_structured(prompt, ActionPackage)
    validate_recommendations(package, {item["finding_id"] for item in state["findings"]})

    db = SessionLocal()
    try:
        db.add(
            AgentAction(
                session_id=state["session_id"],
                stage="act",
                action_type="evidence_linked_action_plan",
                input_summary=f"{len(state['findings'])} findings",
                output_summary=(
                    f"{len(package.recommendations)} recommendations, {len(package.limitations)} limitations, "
                    f"and {len(package.monitoring_metrics)} monitoring measures"
                ),
            )
        )
        db.commit()
    finally:
        db.close()
    return {
        "action_package": package.model_dump(mode="json"),
        "recommendations": [item.model_dump(mode="json") for item in package.recommendations],
        "limitations": package.limitations,
        "monitoring_metrics": package.monitoring_metrics,
    }
