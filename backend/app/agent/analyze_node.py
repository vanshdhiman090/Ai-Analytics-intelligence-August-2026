"""Analyze phase: approve a coverage-checked plan, then calculate with controlled code."""

from __future__ import annotations

import json
from typing import TypedDict

from langgraph.types import interrupt
from sqlalchemy import func

from app.core.database import SessionLocal
from app.domain.contracts import AnalysisPlan, FindingSet
from app.models.schema import AgentAction, Checkpoint
from app.services.analysis import AnalysisPlanError, execute_plan, validate_question_coverage
from app.services.llm import generate_structured
from app.services.run_state import mark_stage
from app.services.tabular import load_dataframe
from app.services.progress import emit_sync


class AnalyzeState(TypedDict, total=False):
    session_id: str
    business_question: str
    analysis_brief: dict
    schema_profile: dict
    cleaned_path: str
    analysis_plan: dict
    pending_analysis_checkpoint_id: str
    analysis_plan_feedback: str
    evidence: list
    findings: list
    analysis_summary: str
    additional_deliverables: list


def planner_prompt(state: AnalyzeState, validation_error: str | None = None) -> str:
    correction = f"\nPrevious plan was rejected or needs revision: {validation_error}\nCorrect that issue." if validation_error else ""
    return (
        "Create a concise analysis plan that answers every explicit part of the confirmed question using only the "
        "supplied columns. Every dataset column directly named in the question must appear in at least one operation. "
        "Choose only these safe operations: summary, grouped_aggregate, trend, period_comparison, distribution, "
        "outlier_analysis, correlation, kpi_ratio, statistical_comparison, segment_change. Use grouped_aggregate for segment comparisons and contributions; it returns "
        "rank, sample count, and share of total when meaningful. Use trend for multi-period movement and "
        "period_comparison for the latest period versus its prior observed period. Set time_grain to auto unless the "
        "question specifies day, week, month, quarter, or year. Use distribution for spread, outlier_analysis only "
        "when unusual observations matter, and correlation only for two numeric columns and never as causal proof. "
        "Use kpi_ratio for rates calculated from an explicit numerator and denominator, never an average of row-level rates. "
        "Use statistical_comparison only for two explicitly named groups and provide baseline_value and comparison_value. "
        "Use segment_change when the question asks which segment drove movement between the latest two periods. "
        "Every requested metric needs the correct aggregation and comparison baseline. Never invent columns, targets, "
        "denominators, or business metrics. Prefer 2-6 non-duplicative operations that cover the question.\n\n"
        f"Confirmed question: {state['business_question']}\n"
        f"Analysis brief: {json.dumps(state.get('analysis_brief', {}), ensure_ascii=False)}\n"
        f"User-selected analytical objectives: {json.dumps(state.get('analysis_objectives', []), ensure_ascii=False)}\n"
        f"Dataset profile: {json.dumps(state['schema_profile'], ensure_ascii=False)}{correction}"
    )


def _validated_plan(state: AnalyzeState, feedback: str | None = None) -> tuple[AnalysisPlan, list]:
    frame = load_dataframe(state["cleaned_path"])
    validation_error = feedback
    for _ in range(3):
        plan = generate_structured(planner_prompt(state, validation_error), AnalysisPlan)
        try:
            validate_question_coverage(frame, plan, state["business_question"])
            return plan, execute_plan(frame, plan)
        except AnalysisPlanError as exc:
            validation_error = str(exc)
    raise AnalysisPlanError(validation_error or "The analysis plan could not be executed")


def _plan_question(plan: AnalysisPlan) -> str:
    operations = "\n".join(
        f"{item.operation_id}. {item.kind} | metric: {item.metric_column or 'n/a'} | "
        f"dimension/time: {item.dimension_column or item.time_column or 'n/a'} | "
        f"denominator: {item.denominator_column or 'n/a'} | {item.rationale}"
        for item in plan.operations
    )
    coverage = "\n".join(f"- {item}" for item in plan.question_coverage)
    return (
        "Review the proposed analysis plan before calculations begin.\n\n"
        f"Objective: {plan.objective}\n\nOperations:\n{operations}\n\nQuestion coverage:\n{coverage}\n\n"
        "Type Confirm to approve, or describe the change you want. Requested changes will be validated against the dataset."
    )


def plan_analysis_node(state: AnalyzeState) -> AnalyzeState:
    mark_stage(state["session_id"], "analyze")
    emit_sync(state["session_id"], "analyze", "Generating and validating analysis plan…")
    plan, _ = _validated_plan(state)
    db = SessionLocal()
    try:
        checkpoint = Checkpoint(session_id=state["session_id"], stage="analyze", question=_plan_question(plan))
        db.add(checkpoint)
        db.commit()
        return {
            "analysis_plan": plan.model_dump(mode="json"),
            "pending_analysis_checkpoint_id": str(checkpoint.id),
        }
    finally:
        db.close()


def approve_analysis_plan_node(state: AnalyzeState) -> AnalyzeState:
    answer = interrupt(
        {
            "stage": "analyze",
            "question": _plan_question(AnalysisPlan.model_validate(state["analysis_plan"])),
            "pending_checkpoint_id": state["pending_analysis_checkpoint_id"],
        }
    )
    db = SessionLocal()
    try:
        checkpoint = db.query(Checkpoint).filter(Checkpoint.id == state["pending_analysis_checkpoint_id"]).first()
        if checkpoint is None:
            raise RuntimeError("Analysis-plan checkpoint no longer exists")
        checkpoint.answer = answer
        checkpoint.resolved_at = func.now()
        db.commit()
    finally:
        db.close()
    return {"analysis_plan_feedback": answer}


def validate_finding_citations(findings: FindingSet, evidence_ids: set[str]) -> None:
    for finding in findings.findings:
        unknown = set(finding.evidence_ids) - evidence_ids
        if unknown:
            raise ValueError(f"Finding {finding.finding_id} cites unknown evidence: {sorted(unknown)}")


def calibrate_finding_confidence(findings: FindingSet, evidence: list) -> FindingSet:
    """Prevent prose confidence from exceeding the quality of its cited calculations."""
    quality = {item.evidence_id: item.quality_status for item in evidence}
    for finding in findings.findings:
        cited = [quality.get(evidence_id, "insufficient") for evidence_id in finding.evidence_ids]
        if "insufficient" in cited:
            finding.confidence = "low"
            finding.caveats.append("At least one cited calculation has insufficient analytical support")
        elif "caution" in cited and finding.confidence == "high":
            finding.confidence = "medium"
            finding.caveats.append("Confidence capped because at least one cited calculation requires caution")
    return findings


def analyze_node(state: AnalyzeState) -> AnalyzeState:
    mark_stage(state["session_id"], "analyze")
    emit_sync(state["session_id"], "analyze", "Running approved statistical operations…")
    feedback = (state.get("analysis_plan_feedback") or "Confirm").strip()
    if feedback.lower() in {"confirm", "confirmed", "approve", "approved", "yes"}:
        plan = AnalysisPlan.model_validate(state["analysis_plan"])
        frame = load_dataframe(state["cleaned_path"])
        validate_question_coverage(frame, plan, state["business_question"])
        evidence = execute_plan(frame, plan)
    else:
        plan, evidence = _validated_plan(state, f"Human requested these plan changes: {feedback}")

    evidence_payload = [item.model_dump(mode="json") for item in evidence]
    findings_prompt = (
        "Write evidence-grounded findings that address every covered part of the confirmed question. Every finding "
        "must cite supplied evidence IDs and use only values present in the evidence. Interpret rank, contribution, "
        "change, sample size, uncertainty, and concentration only when those fields are present. Respect quality_status "
        "and caveats: exploratory or small-sample evidence cannot support high-confidence claims. Do not create causal "
        "explanations, benchmarks, targets, or external facts. Separate observed patterns from possible explanations and "
        "explicitly list any still-unanswered part of the question.\n\n"
        f"Question: {state['business_question']}\nEvidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
    )
    finding_set = generate_structured(findings_prompt, FindingSet)
    validate_finding_citations(finding_set, {item.evidence_id for item in evidence})
    finding_set = calibrate_finding_confidence(finding_set, evidence)

    db = SessionLocal()
    try:
        db.add(
            AgentAction(
                session_id=state["session_id"],
                stage="analyze",
                action_type="approved_statistical_analysis",
                input_summary=f"Business question: {state['business_question']}",
                output_summary=f"Executed {len(plan.operations)} approved operations and produced {len(finding_set.findings)} evidence-linked findings",
                code_executed="Allow-listed analysis executor; no model-authored code",
            )
        )
        db.commit()
    finally:
        db.close()

    return {
        "analysis_plan": plan.model_dump(mode="json"),
        "evidence": evidence_payload,
        "findings": [item.model_dump(mode="json") for item in finding_set.findings],
        "analysis_summary": finding_set.summary,
        "additional_deliverables": finding_set.unanswered_questions,
    }
