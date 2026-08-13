"""AnalyzeAgent — Statistical Analysis & Execution Specialist."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func

from app.agent.subagents.base import BaseSubAgent
from app.core.database import SessionLocal
from app.domain.contracts import AnalysisPlan, FindingSet
from app.models.schema import AgentAction, Checkpoint
from app.services.analysis import AnalysisPlanError, apply_comparison_context, execute_plan, validate_question_coverage
from app.services.comparison_context import ComparisonContext
from app.services.llm import generate_structured
from app.services.progress import emit_sync
from app.services.run_state import mark_stage
from app.services.tabular import load_dataframe

logger = logging.getLogger(__name__)


def planner_prompt(state: dict[str, Any], validation_error: str | None = None) -> str:
    correction = (
        f"\nPrevious plan was rejected or needs revision: {validation_error}\nCorrect that issue."
        if validation_error
        else ""
    )
    root_cause_guidance = (
        "\nThis is a root-cause diagnostic. Build a driver-oriented plan using observed data: quantify the target "
        "metric by the named segment, add relevant time movement when a date field exists, and compare the most "
        "decision-relevant available product/channel/geography dimensions. For associations within a named segment, "
        "use grouped_aggregate with dimension_column set to that segment and secondary_dimension_column set to the "
        "product, retailer, channel, or other driver field. Use separate intersection operations for important driver "
        "fields. Use segment_change only when a valid time "
        "field and two observed periods exist. The result may identify mathematical contributors and associations, "
        "not causal mechanisms. Never return a plan with zero operations.\n"
        if "root_cause" in state.get("analysis_objectives", []) else ""
    )
    return (
        "Create a concise analysis plan that answers every explicit part of the confirmed question using only the "
        "supplied columns. Every dataset column directly named in the question must appear in at least one operation. "
        "Choose only these safe operations: summary, grouped_aggregate, trend, period_comparison, distribution, "
        "outlier_analysis, correlation, kpi_ratio, statistical_comparison, segment_change. Use grouped_aggregate for segment comparisons and contributions; it returns "
        "rank, sample count, and share of total when meaningful. Use trend for multi-period movement and "
        "period_comparison for a specified comparison pair when provided, otherwise the latest period versus its prior observed period. Set time_grain to auto unless the "
        "question specifies day, week, month, quarter, or year. Use distribution for spread, outlier_analysis only "
        "when unusual observations matter, and correlation only for two numeric columns and never as causal proof. "
        "Use kpi_ratio for rates calculated from an explicit numerator and denominator, never an average of row-level rates. "
        "Use statistical_comparison only for two explicitly named groups and provide baseline_value and comparison_value. "
        "Use segment_change when the question asks which segment contributed to movement between the specified comparison periods (or latest two only if none were specified). "
        "Every requested metric needs the correct aggregation and comparison baseline. Never invent columns, targets, "
        "denominators, or business metrics. Prefer 2-6 non-duplicative operations that cover the question."
        f"{root_cause_guidance}\n"
        f"Confirmed question: {state['business_question']}\n"
        f"Analysis brief: {json.dumps(state.get('analysis_brief', {}), ensure_ascii=False)}\n"
        f"User-selected analytical objectives: {json.dumps(state.get('analysis_objectives', []), ensure_ascii=False)}\n"
        f"Governed comparison context: {json.dumps(state.get('comparison_context'), ensure_ascii=False)}\n"
        f"Dataset profile: {json.dumps(state['schema_profile'], ensure_ascii=False)}{correction}\n\n"
        f"{BaseSubAgent.memory_context(state)}"
    )


def validated_plan(state: dict[str, Any], feedback: str | None = None) -> tuple[AnalysisPlan, list]:
    frame = load_dataframe(state["cleaned_path"])
    validation_error = feedback
    for _ in range(3):
        plan = generate_structured(planner_prompt(state, validation_error), AnalysisPlan)
        try:
            context = ComparisonContext.model_validate(state["comparison_context"]) if state.get("comparison_context") else None
            plan = apply_comparison_context(plan, context)
            validate_question_coverage(frame, plan, state["business_question"])
            return plan, execute_plan(frame, plan)
        except AnalysisPlanError as exc:
            validation_error = str(exc)
    raise AnalysisPlanError(validation_error or "The analysis plan could not be executed")


def plan_question(plan: AnalysisPlan) -> str:
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


def validate_finding_citations(findings: FindingSet, evidence_ids: set[str]) -> None:
    for finding in findings.findings:
        unknown = set(finding.evidence_ids) - evidence_ids
        if unknown:
            raise ValueError(f"Finding {finding.finding_id} cites unknown evidence: {sorted(unknown)}")


def calibrate_finding_confidence(findings: FindingSet, evidence: list) -> FindingSet:
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


class AnalyzeAgent(BaseSubAgent):
    name = "AnalyzeAgent"
    domain_role = "Statistical Analysis & Execution Specialist"
    description = "Formulates coverage-checked analysis plans and executes allow-listed mathematical operations."

    def plan_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        mark_stage(state["session_id"], "analyze")
        emit_sync(state["session_id"], "analyze", "[AnalyzeAgent] Formulating coverage-checked analysis plan…")
        plan, _ = validated_plan(state)
        db = SessionLocal()
        try:
            checkpoint = Checkpoint(
                session_id=state["session_id"], stage="analyze", question=plan_question(plan)
            )
            db.add(checkpoint)
            db.commit()
            return {
                "analysis_plan": plan.model_dump(mode="json"),
                "pending_analysis_checkpoint_id": str(checkpoint.id),
            }
        finally:
            db.close()

    def run_analysis(self, state: dict[str, Any]) -> dict[str, Any]:
        mark_stage(state["session_id"], "analyze")
        emit_sync(state["session_id"], "analyze", "[AnalyzeAgent] Executing statistical calculations and building evidence…")
        feedback = (state.get("analysis_plan_feedback") or "Confirm").strip()
        if feedback.lower() in {"confirm", "confirmed", "approve", "approved", "yes"}:
            plan = AnalysisPlan.model_validate(state["analysis_plan"])
            context = ComparisonContext.model_validate(state["comparison_context"]) if state.get("comparison_context") else None
            plan = apply_comparison_context(plan, context)
            frame = load_dataframe(state["cleaned_path"])
            validate_question_coverage(frame, plan, state["business_question"])
            evidence = execute_plan(frame, plan)
        else:
            plan, evidence = validated_plan(state, f"Human requested these plan changes: {feedback}")

        evidence_payload = [item.model_dump(mode="json") for item in evidence]
        findings_prompt = (
            "Write evidence-grounded findings that address every covered part of the confirmed question. Every finding "
            "must cite supplied evidence IDs and use only values present in the evidence. Interpret rank, contribution, "
            "change, sample size, uncertainty, and concentration only when those fields are present. Respect quality_status "
            "and caveats: exploratory or small-sample evidence cannot support high-confidence claims. Do not create causal "
            "explanations, benchmarks, targets, or external facts. Separate observed patterns from possible explanations and "
            "explicitly list any still-unanswered part of the question. For segment_change evidence, describe a segment as "
            "'contributing to observed movement' rather than saying it caused or drove a business outcome.\n\n"
            f"Question: {state['business_question']}\nEvidence: {json.dumps(evidence_payload, ensure_ascii=False)}"
            f"\n\n{self.memory_context(state)}"
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

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        phase = kwargs.get("phase", "plan")
        if phase == "run":
            return self.run_analysis(state)
        return self.plan_analysis(state)
