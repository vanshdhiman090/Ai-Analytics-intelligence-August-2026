"""RootCauseAgent — Specialized Root Cause Analytics Investigator."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.subagents.base import BaseSubAgent
from app.agent.subagents.analyze_agent import AnalyzeAgent
from app.domain.revenue_semantics import build_revenue_semantic_context, canonical_revenue_metric
from app.services.root_cause import build_root_cause_report, run_single_level_investigation
from app.services.tabular import load_dataframe

logger = logging.getLogger(__name__)

# The user-provided system prompt for the Root Cause Analytics Specialist.
ROOT_CAUSE_PROMPT = """ROOT CAUSE ANALYTICS SPECIALIST — SYSTEM PROMPT

ROLE

You are the Root Cause Analytics Specialist, a senior analytical investigation agent.

Operate with the judgment, skepticism, discipline, and pattern-recognition expected from an elite data analytics expert with decades of experience investigating business KPI movements, operational incidents, revenue problems, data anomalies, funnel deterioration, customer behavior changes, forecasting gaps, and performance issues.

You are not a general-purpose chatbot.
You are not a dashboard summarizer.
You are not primarily a report writer.
You are an investigator.

Your responsibility is to determine:
«What changed, where it changed, what mathematically drove the change, what likely caused it, how much impact each driver had, what evidence supports the conclusion, what remains unknown, and what should be investigated next.»

Your conclusions must be based on evidence rather than plausible storytelling.

---
PRIMARY OBJECTIVE
Given a business question, available datasets, schema information, and SQL/Python tools, conduct a rigorous Root Cause Analysis.
Your investigation should move through:
Detection → Validation → Decomposition → Segmentation → Contribution → Hypothesis → Testing → Falsification → Verification → Impact → Conclusion

---
CORE PRINCIPLE
Never confuse Observation with Driver with Root Cause. You must explicitly distinguish them.

---
ANALYTICAL MINDSET
Think like a highly experienced investigator.
Before accepting any explanation, ask:
- Could the underlying data be wrong?
- Could this be normal seasonality?
- Is this percentage movement caused by a tiny denominator?
- Are multiple factors interacting?
- What evidence would disprove my current hypothesis?

Never stop at the first plausible explanation.

---
INVESTIGATION FRAMEWORK
Follow this sequence unless the evidence requires a justified deviation.

STEP 1 — UNDERSTAND THE INCIDENT
Determine the KPI, current value, baseline, absolute/percentage change, and target period.

STEP 2 — VERIFY THE METRIC DEFINITION
Before calculating the KPI, establish its definition.

STEP 3 — CHECK DATA HEALTH FIRST
Before assuming a business problem exists, determine whether the data itself is trustworthy. Check freshness, volume, completeness, uniqueness, and validity.

STEP 4 — DETERMINE WHETHER THE MOVEMENT IS ACTUALLY ABNORMAL
Compare against relevant baselines.

STEP 5 — BUILD / USE THE KPI DRIVER TREE
Break the target KPI into mathematically or operationally meaningful components.

STEP 6 — QUANTIFY FIRST-LEVEL DRIVERS
Determine which part of the KPI equation explains the movement before jumping to segments.

STEP 7 — SEGMENT SYSTEMATICALLY
Investigate meaningful dimensions available in the data (geography, device, acquisition channel, product).

STEP 8 — MEASURE CONTRIBUTION, NOT JUST PERCENTAGE CHANGE
A segment having the largest percentage decline does NOT necessarily make it the main driver. Always quantify absolute contribution.

STEP 9 — INVESTIGATE INTERACTIONS
Investigate intersections when evidence indicates they may materially improve explanatory power.

STEP 10 — GENERATE HYPOTHESES
After finding the affected metric branch and segments, generate plausible mechanisms.

STEP 11 — TEST HYPOTHESES USING DATA
Each hypothesis receives one of: SUPPORTED, PARTIALLY SUPPORTED, REJECTED, UNRESOLVED.

STEP 12 — ACTIVELY TRY TO DISPROVE YOURSELF
Before accepting the leading explanation, search for alternative explanations.

STEP 13 — SEPARATE CONTRIBUTION FROM CAUSALITY
Use precise language. Do not say "Payment failures caused the revenue decline" unless you have causal evidence. Prefer "mathematical driver" or "contributing factor".

STEP 14 — QUANTIFY BUSINESS IMPACT
Calculate lost revenue, affected customers, etc. where possible.

STEP 15 — DETERMINE EXPLAINED VS UNEXPLAINED MOVEMENT
Explicitly preserve unexplained movement. Never force 100% of the KPI movement into your explanation.

STEP 16 — ASSIGN EVIDENCE STRENGTH
High / Medium / Low.

STEP 17 — PRODUCE THE ROOT CAUSE REPORT
Every completed investigation must contain:
- Incident
- Baseline
- KPI Movement
- Data Health
- Metric Decomposition
- Primary Driver
- Affected Segment
- Contribution
- Supporting Evidence
- Hypotheses Tested
- Alternative Explanations Considered
- Secondary Drivers
- Unexplained Movement
- Business Impact
- Evidence Strength
- Recommended Next Investigation / Action
- Limitations
- Analysis Trail

FAILURE CONDITIONS
You MUST say "I cannot determine the root cause from the available evidence." when appropriate (e.g. data quality is unacceptable, comparison period invalid).

TOOL USAGE
LLM proposes. Tools calculate. Evidence decides.
You have access to a safe structured pandas tool `query_dataset` which you must use to fetch data and verify your hypotheses. Never hallucinate data.

---
WHAT TO REMEMBER
After an investigation, save durable lessons such as metric knowledge, business knowledge, known data issues.

---
SELF-CHECK BEFORE FINALIZING
Before returning any conclusion, verify: Is every important claim backed by evidence?
"""

class RootCauseAgent(BaseSubAgent):
    """Executes the rigorous Root Cause Analytics Specialist methodology."""

    # Runtime identity must exactly match the declarative hierarchy registry.
    name = "RootCauseAgent"
    domain_role = "Root Cause Analytics Specialist"
    description = "Conducts deep-dive investigations to determine mathematical drivers and root causes of metric movements."

    @staticmethod
    def _rca_semantic_definition(result: dict[str, Any]) -> dict[str, Any] | None:
        operations = (result.get("analysis_plan") or {}).get("operations") or []
        evidence_by_operation = {
            item.get("operation_id"): item for item in result.get("evidence") or []
        }
        for operation in operations:
            if operation.get("kind") != "segment_change":
                continue
            evidence = evidence_by_operation.get(operation.get("operation_id"), {})
            grain = (evidence.get("diagnostics") or {}).get("time_grain")
            if grain not in {"day", "week", "month", "quarter", "year"}:
                grain = operation.get("time_grain")
            if grain not in {"day", "week", "month", "quarter", "year"}:
                grain = "month"
            return {
                "metric_name": operation.get("metric_column"),
                "metric_column": operation.get("metric_column"),
                "time_column": operation.get("time_column"),
                "driver_column": operation.get("dimension_column"),
                "aggregation": "sum",
                "time_grain": grain,
            }
        return None

    @staticmethod
    def _metric_semantics(state: dict[str, Any], definition: dict[str, Any] | None) -> dict[str, Any]:
        metric_column = str((definition or {}).get("metric_column") or "")
        if metric_column.lower() not in {"net_revenue", "revenue_net"}:
            return {
                "status": "generic_metric",
                "metric_column": metric_column or None,
                "message": "The investigation uses the approved operation definition; the Revenue V0 contract is not applicable.",
            }
        currency = str(state.get("revenue_reporting_currency") or "").strip().upper()
        timezone = str(state.get("revenue_timezone") or "").strip()
        if not currency or not timezone:
            return {
                "status": "abstained",
                "metric_id": "revenue",
                "message": "Revenue semantics require an explicit reporting currency and IANA timezone; neither value is guessed.",
                "missing_policy_fields": [
                    name for name, value in (
                        ("revenue_reporting_currency", currency),
                        ("revenue_timezone", timezone),
                    ) if not value
                ],
            }
        context = build_revenue_semantic_context(
            canonical_revenue_metric(reporting_currency=currency, timezone=timezone),
            {"approved_dataset": state.get("schema_profile") or {}},
        )
        return {
            "status": context.inference.status,
            **context.model_dump(mode="json"),
        }

    @staticmethod
    def _abstention_report(message: str) -> dict[str, Any]:
        return {
            "contract_version": "0.1",
            "status": "abstained",
            "conclusion": {
                "determination": "inconclusive",
                "statement": "I cannot determine the root cause from the available evidence.",
                "causal_claim_allowed": False,
                "evidence_strength": "low",
                "abstention_reason": message,
            },
            "drivers": [],
            "hypotheses": [],
            "next_investigations": ["Approve a time-based additive segment decomposition with at least two complete periods."],
            "limitations": [message, "Mathematical contribution does not by itself establish causality."],
            "analysis_trail": ["Applied the RCA semantic and abstention gate before drawing a conclusion."],
        }

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        logger.info("Executing RootCauseAgent through the validated deterministic analysis engine")
        # Milestone 1 is intentionally a direct deterministic runtime path. It
        # bypasses the legacy LLM planning route when a bounded investigation
        # request has been supplied.
        if state.get("investigation_request"):
            investigation = run_single_level_investigation(
                load_dataframe(state["cleaned_path"]), state["investigation_request"]
            )
            return {"investigation_state": investigation.model_dump(mode="json")}
        # Root-cause work uses a specialist planning brief, but calculation,
        # evidence and findings must use the same typed contracts and
        # allow-listed executor as every other publishable analysis.
        result = AnalyzeAgent().run_analysis(state)
        definition = self._rca_semantic_definition(result)
        metric_semantics = self._metric_semantics(state, definition)
        if definition is None:
            report = self._abstention_report(
                "The approved plan contains no additive segment_change operation suitable for deterministic RCA."
            )
        elif metric_semantics.get("status") == "abstained":
            report = self._abstention_report(
                str(metric_semantics.get("message") or "The governed metric definition is incomplete or ambiguous.")
            )
        else:
            report = build_root_cause_report(
                load_dataframe(state["cleaned_path"]),
                definition,
                evidence=result.get("evidence") or (),
                state=state,
            )
        return {
            **result,
            "metric_semantics": metric_semantics,
            "root_cause_report": report,
        }
