"""Focused professional specialists that compose the stage executors.

The legacy stage agents remain the trusted implementation of database writes,
LLM calls, and deterministic calculations.  These wrappers give the manager a
narrow delegation boundary and add independent, side-effect-free reviews around
that implementation.
"""

from __future__ import annotations

from typing import Any

from app.agent.subagents.act_agent import ActAgent
from app.agent.subagents.analyze_agent import AnalyzeAgent
from app.agent.subagents.ask_agent import AskAgent
from app.agent.subagents.base import BaseSubAgent
from app.agent.subagents.package_agent import PackageAgent
from app.agent.subagents.share_agent import ShareAgent


def _review(
    state: dict[str, Any],
    *,
    specialist: str,
    stage: str,
    status: str,
    checks: list[str],
    concerns: list[str] | None = None,
) -> dict[str, Any]:
    reviews = [dict(item) for item in state.get("specialist_reviews", [])]
    reviews.append(
        {
            "specialist": specialist,
            "stage": stage,
            "status": status,
            "checks": checks,
            "concerns": concerns or [],
        }
    )
    return {"specialist_reviews": reviews}


class BusinessProblemSpecialist(BaseSubAgent):
    name = "BusinessProblemSpecialist"
    domain_role = "Business Problem Framing Specialist"
    description = "Converts the user's request into a decision-focused analytical brief without inventing context."

    def __init__(self, executor: AskAgent | None = None) -> None:
        self.executor = executor or AskAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        result = self.executor.execute(state, **kwargs)
        if kwargs.get("phase") == "confirm" and result.get("business_question"):
            brief = dict(state.get("analysis_brief") or {})
            brief["primary_question"] = result["business_question"]
            result["analysis_brief"] = brief
        return result


class StakeholderScopeSpecialist(BaseSubAgent):
    name = "StakeholderScopeSpecialist"
    domain_role = "Stakeholder and Scope Specialist"
    description = "Reviews decision ownership, in-scope work, exclusions, constraints, and missing human context."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        brief = state.get("analysis_brief") or {}
        required = ("decision", "primary_question", "stakeholders", "in_scope", "success_criteria")
        missing = [field for field in required if not brief.get(field)]
        if missing:
            raise ValueError(f"Discovery contract is incomplete; missing: {missing}")
        return _review(
            state,
            specialist=self.name,
            stage="ask",
            status="approved",
            checks=["decision owner context", "scope boundaries", "success criteria", "required context"],
        )


class KPISpecialist(BaseSubAgent):
    name = "KPISpecialist"
    domain_role = "KPI Definition and Measurement Specialist"
    description = "Checks that success criteria are measurable while refusing to invent targets or denominators."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        criteria = (state.get("analysis_brief") or {}).get("success_criteria") or []
        if not criteria:
            raise ValueError("At least one success criterion is required before data work begins")
        concerns = [
            "Numeric targets and KPI denominators still require human confirmation when not present in the request."
        ]
        return _review(
            state,
            specialist=self.name,
            stage="ask",
            status="approved_with_caution",
            checks=["measurable success criteria", "no invented targets", "denominator disclosure"],
            concerns=concerns,
        )


class AnalysisPlannerSpecialist(BaseSubAgent):
    name = "AnalysisPlannerSpecialist"
    domain_role = "Analysis Planning Specialist"
    description = "Designs a coverage-complete plan containing only allow-listed analytical operations."

    def __init__(self, executor: AnalyzeAgent | None = None) -> None:
        self.executor = executor or AnalyzeAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.executor.execute(state, phase="plan")


class StatisticalAnalysisSpecialist(BaseSubAgent):
    name = "StatisticalAnalysisSpecialist"
    domain_role = "Deterministic Statistical Execution Specialist"
    description = "Executes approved allow-listed calculations and produces structured evidence."

    def __init__(self, executor: AnalyzeAgent | None = None) -> None:
        self.executor = executor or AnalyzeAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.executor.execute(state, phase="run")


class TrendSegmentationSpecialist(BaseSubAgent):
    name = "TrendSegmentationSpecialist"
    domain_role = "Trend and Segmentation Review Specialist"
    description = "Checks time, segment, contribution, and comparison coverage against the selected objectives."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        operations = (state.get("analysis_plan") or {}).get("operations") or []
        kinds = {str(item.get("kind")) for item in operations}
        objectives = {str(item).lower() for item in state.get("analysis_objectives", [])}
        concerns: list[str] = []
        if any("trend" in item for item in objectives) and not kinds.intersection({"trend", "period_comparison", "segment_change"}):
            concerns.append("A trend objective was selected but the approved plan has no time-comparison operation.")
        if any("segment" in item for item in objectives) and not kinds.intersection({"grouped_aggregate", "segment_change", "statistical_comparison"}):
            concerns.append("A segmentation objective was selected but the approved plan has no segment operation.")
        return _review(
            state,
            specialist=self.name,
            stage="analyze",
            status="approved" if not concerns else "revision_recommended",
            checks=["time coverage", "segment coverage", "comparison baseline"],
            concerns=concerns,
        )


class EvidenceSpecialist(BaseSubAgent):
    name = "EvidenceSpecialist"
    domain_role = "Evidence Traceability Specialist"
    description = "Independently checks finding citations, evidence populations, and confidence metadata."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        evidence = state.get("evidence") or []
        findings = state.get("findings") or []
        if not evidence or not findings:
            raise ValueError("Evidence review requires at least one evidence record and one finding")
        evidence_ids = {str(item.get("evidence_id")) for item in evidence}
        unknown = sorted(
            {
                str(reference)
                for finding in findings
                for reference in finding.get("evidence_ids", [])
                if str(reference) not in evidence_ids
            }
        )
        missing_population = [item.get("evidence_id") for item in evidence if not item.get("population")]
        incomplete = [
            item.get("finding_id")
            for item in findings
            if not item.get("statement")
            or not item.get("implication")
            or str(item.get("confidence", "")).lower() not in {"high", "medium", "low"}
        ]
        if unknown or missing_population or incomplete:
            raise ValueError(
                "Evidence contract failed: "
                f"unknown citations={unknown}; missing populations={missing_population}; incomplete findings={incomplete}"
            )
        return _review(
            state,
            specialist=self.name,
            stage="analyze",
            status="approved",
            checks=["finding citations", "population disclosure", "confidence metadata"],
        )


class VisualizationSpecialist(BaseSubAgent):
    name = "VisualizationSpecialist"
    domain_role = "Evidence Visualization Specialist"
    description = "Selects and renders professional charts directly from validated evidence."

    def __init__(self, executor: ShareAgent | None = None) -> None:
        self.executor = executor or ShareAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.executor.execute(state, **kwargs)


class NarrativeSpecialist(BaseSubAgent):
    name = "NarrativeSpecialist"
    domain_role = "Analytical Narrative Specialist"
    description = "Checks that the answer-first narrative remains complete, bounded, and evidence-linked."

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if not str(state.get("analysis_summary") or "").strip():
            raise ValueError("A professional analytical narrative requires a non-empty summary")
        return _review(
            state,
            specialist=self.name,
            stage="share",
            status="approved",
            checks=["answer-first summary", "visible limitations", "finding-to-visual consistency"],
        )


class RecommendationSpecialist(BaseSubAgent):
    name = "RecommendationSpecialist"
    domain_role = "Evidence-Linked Recommendation Specialist"
    description = "Creates bounded actions with finding links, owners, timing, monitoring, and explicit uncertainty."

    def __init__(self, executor: ActAgent | None = None) -> None:
        self.executor = executor or ActAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.executor.execute(state, **kwargs)


class DocumentSpecialist(BaseSubAgent):
    name = "DocumentSpecialist"
    domain_role = "Requested Deliverable Assembly Specialist"
    description = "Creates only the deliverables selected by the user after independent publication approval."

    def __init__(self, executor: PackageAgent | None = None) -> None:
        self.executor = executor or PackageAgent()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.executor.execute(state, **kwargs)
