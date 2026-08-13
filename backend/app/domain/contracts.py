"""Versioned, validated contracts shared by the analytics workflow stages."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class Stakeholder(BaseModel):
    name: str = Field(description="Person or group name; use 'Unspecified' when unknown.")
    role: str
    decision_interest: str


class AnalysisBrief(BaseModel):
    contract_version: Literal["1.0", "1.0.0"] = "1.0"
    objective: str = Field(min_length=10)
    decision: str = Field(min_length=10, description="The decision this analysis should support.")
    primary_question: str = Field(min_length=10)
    stakeholders: list[Stakeholder] = Field(min_length=1)
    success_criteria: list[str] = Field(min_length=1)
    in_scope: list[str] = Field(min_length=1)
    out_of_scope: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    required_context: list[str] = Field(
        default_factory=list,
        description="External facts that must be supplied by a human rather than inferred.",
    )


class EvidenceRef(BaseModel):
    evidence_id: str = Field(pattern=r"^E\d+$")
    operation_id: str
    metric: str
    value: float | int | str
    unit: str | None = None
    population: str
    method: str


class AnalysisOperation(BaseModel):
    operation_id: str = Field(pattern=r"^OP\d+$")
    kind: Literal[
        "summary",
        "grouped_aggregate",
        "trend",
        "period_comparison",
        "distribution",
        "outlier_analysis",
        "correlation",
        "kpi_ratio",
        "statistical_comparison",
        "segment_change",
    ]
    metric_column: str | None = None
    dimension_column: str | None = None
    secondary_dimension_column: str | None = None
    time_column: str | None = None
    denominator_column: str | None = None
    baseline_value: str | None = None
    comparison_value: str | None = None
    baseline_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    comparison_period: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    period_source: Literal["explicit_user_request", "automatic_latest"] | None = None
    aggregation: Literal["sum", "mean", "median", "count", "min", "max"] = "mean"
    time_grain: Literal["auto", "day", "week", "month", "quarter", "year"] = "month"
    ratio_scale: Literal[1, 100, 1000] = 100
    limit: int = Field(default=20, ge=2, le=50)
    rationale: str


class AnalysisPlan(BaseModel):
    contract_version: Literal["1.0", "1.0.0"] = "1.0"
    objective: str
    operations: list[AnalysisOperation] = Field(min_length=1, max_length=8)
    question_coverage: list[str] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)


class OperationResult(BaseModel):
    evidence_id: str = Field(pattern=r"^E\d+$")
    operation_id: str = Field(pattern=r"^OP\d+$")
    kind: str
    title: str
    columns: list[str]
    rows: list[dict]
    method: str
    population: str
    caveats: list[str] = Field(default_factory=list)
    quality_status: Literal["ready", "caution", "insufficient"] = "ready"
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    finding_id: str = Field(pattern=r"^F\d+$")
    statement: str
    implication: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    caveats: list[str] = Field(default_factory=list)


class FindingSet(BaseModel):
    summary: str
    findings: list[Finding] = Field(min_length=1)
    unanswered_questions: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    recommendation_id: str = Field(pattern=r"^R\d+$")
    action: str
    rationale: str
    finding_ids: list[str] = Field(min_length=1)
    owner_role: str
    timeframe: str
    expected_impact: Literal["high", "medium", "low", "unknown"]
    effort: Literal["high", "medium", "low", "unknown"]


class ActionPackage(BaseModel):
    recommendations: list[Recommendation]
    limitations: list[str] = Field(min_length=1)
    monitoring_metrics: list[str] = Field(default_factory=list)


class DecisionPackage(BaseModel):
    brief: AnalysisBrief
    evidence: list[EvidenceRef]
    findings: list[Finding]
    recommendations: list[Recommendation]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_traceability(self):
        evidence_ids = {item.evidence_id for item in self.evidence}
        finding_ids = {item.finding_id for item in self.findings}
        for finding in self.findings:
            unknown = set(finding.evidence_ids) - evidence_ids
            if unknown:
                raise ValueError(f"Finding {finding.finding_id} cites unknown evidence: {sorted(unknown)}")
        for recommendation in self.recommendations:
            unknown = set(recommendation.finding_ids) - finding_ids
            if unknown:
                raise ValueError(
                    f"Recommendation {recommendation.recommendation_id} cites unknown findings: {sorted(unknown)}"
                )
        return self
