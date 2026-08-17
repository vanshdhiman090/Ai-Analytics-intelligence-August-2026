"""Stable public V1 contracts for the RCA API.

These DTOs intentionally do not inherit from internal investigation contracts.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.period_labels import PeriodGrain, validate_period_label


RCAClaimTypeV1 = Literal[
    "mathematical_observation",
    "leading_tested_contributor",
    "robust_descriptive_explanation",
    "competing_explanations",
    "data_quality_abstention",
    "inconclusive",
]
RCATerminalStatusV1 = Literal[
    "completed",
    "completed_with_caveats",
    "inconclusive",
    "blocked_by_data_quality",
    "blocked_by_reconciliation",
    "bounded_by_max_depth",
    "no_material_driver",
    "incomplete_testing",
]
RCAReadinessReasonV1 = Literal[
    "data_quality",
    "incomplete_testing",
    "reconciliation",
    "competing_explanations",
    "insufficient_evidence",
    "verification_incomplete",
]
RCARobustnessStatusV1 = Literal[
    "robust",
    "robust_with_caveats",
    "weakened",
    "competing",
    "not_verified",
    "abstained",
]
RCAEvidenceStrengthV1 = Literal["strong", "moderate", "weak", "insufficient"]
RCACaveatCodeV1 = Literal[
    "material_offsets",
    "leading_segment_remainder",
    "competing_decomposition",
    "maximum_depth_boundary",
    "downstream_scope_data_quality",
    "nonblocking_data_quality",
    "insufficient_evidence",
    "incomplete_testing",
    "reconciliation_failure",
    "verification_not_completed",
    "no_material_driver",
    "robustness_applies_to_upstream_scope_only",
]
RCANextActionV1 = Literal[
    "none_required",
    "inspect_competing_explanation",
    "improve_data_quality",
    "collect_more_data",
    "expand_candidate_dimensions",
    "increase_investigation_depth",
    "review_large_offsets",
    "complete_required_testing",
    "repair_reconciliation",
]
RCADataQualityCodeV1 = Literal[
    "required_fields_missing",
    "invalid_dates",
    "requested_period_missing",
    "comparison_coverage_incomplete",
    "metric_completeness_failed",
    "insufficient_scope_rows",
    "other_bounded_quality_issue",
]


class RCAAPIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _validate_column_name(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("Column names cannot contain control characters")
    return value


class RCAKPIRequestV1(RCAAPIModel):
    name: str = Field(min_length=1, max_length=128)
    metric_column: str = Field(min_length=1, max_length=256)
    time_column: str = Field(min_length=1, max_length=256)
    time_grain: PeriodGrain
    aggregation: Literal["sum"] = "sum"
    unit: str | None = Field(default=None, max_length=32)

    @field_validator("metric_column", "time_column")
    @classmethod
    def valid_column_name(cls, value: str) -> str:
        return _validate_column_name(value)


class RCAInvestigationRequestV1(RCAAPIModel):
    dataset_id: UUID
    goal: str = Field(min_length=3, max_length=500)
    kpi: RCAKPIRequestV1
    baseline_period: str = Field(min_length=4, max_length=10)
    comparison_period: str = Field(min_length=4, max_length=10)
    candidate_dimensions: tuple[str, ...] = Field(min_length=1, max_length=12)

    @field_validator("candidate_dimensions")
    @classmethod
    def valid_dimensions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_column_name(value) for value in values)

    @model_validator(mode="after")
    def validate_scope(self) -> "RCAInvestigationRequestV1":
        validate_period_label(self.baseline_period, self.kpi.time_grain)
        validate_period_label(self.comparison_period, self.kpi.time_grain)
        if self.baseline_period == self.comparison_period:
            raise ValueError("Baseline and comparison periods must differ")
        if len(self.candidate_dimensions) != len(set(self.candidate_dimensions)):
            raise ValueError("Candidate dimensions must be unique")
        reserved = {self.kpi.metric_column, self.kpi.time_column}
        if reserved.intersection(self.candidate_dimensions):
            raise ValueError("Metric and time columns cannot be candidate dimensions")
        return self


class RCAFilterV1(RCAAPIModel):
    dimension: str
    segment: str


class RCAKPIMovementV1(RCAAPIModel):
    name: str
    unit: str | None = None
    baseline_period: str
    comparison_period: str
    baseline_value: float | None = None
    comparison_value: float | None = None
    signed_change: float | None = None
    evidence_refs: tuple[str, ...] = ()


class RCAPathStepV1(RCAAPIModel):
    depth: int = Field(ge=1)
    source_scope: tuple[RCAFilterV1, ...]
    target_scope: tuple[RCAFilterV1, ...]
    dimension: str
    segment: str
    baseline_value: float
    comparison_value: float
    parent_movement: float
    segment_movement: float
    local_contribution_pct: float | None = None
    global_contribution_pct: float | None = None
    evidence_strength: RCAEvidenceStrengthV1
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class RCALeadingContributorV1(RCAAPIModel):
    source_scope: tuple[RCAFilterV1, ...]
    target_scope: tuple[RCAFilterV1, ...]
    dimension: str
    segment: str
    baseline_value: float
    comparison_value: float
    signed_change: float
    local_contribution_pct: float | None = None
    global_contribution_pct: float | None = None
    evidence_strength: RCAEvidenceStrengthV1
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    # The LLM's own text for why this dimension was worth checking, written
    # BEFORE any test ran against it. It is planning input, not a finding —
    # never a post-hoc justification for why this is the answer. Populated
    # only when the LLM itself proposed this exact winning dimension; null
    # (never a synthesized substitute) whenever the LLM failed, never
    # proposed this dimension, or the winner came from deterministic
    # fallback.
    prioritization_rationale: str | None = Field(default=None, max_length=180)


class RCATargetDecompositionV1(RCAAPIModel):
    source_scope: tuple[RCAFilterV1, ...]
    dimension: str
    parent_movement: float
    dimension_net_movement: float
    leading_segment_movement: float
    remaining_segment_movement: float
    downward_pressure: float
    positive_offsets: float
    reconciliation_residual: float
    reconciles: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class RCARobustnessV1(RCAAPIModel):
    status: RCARobustnessStatusV1
    applies_to_selected_target: bool


class RCAExplanatoryReadinessV1(RCAAPIModel):
    status: Literal["ready", "ready_with_caveats", "not_ready"]
    reason: RCAReadinessReasonV1 | None = None

    @model_validator(mode="after")
    def reason_matches_status(self) -> "RCAExplanatoryReadinessV1":
        if self.status == "not_ready" and self.reason is None:
            raise ValueError("Not-ready status requires a controlled reason")
        if self.status != "not_ready" and self.reason is not None:
            raise ValueError("Ready statuses cannot have a not-ready reason")
        return self


class RCAConclusionV1(RCAAPIModel):
    claim: RCAClaimTypeV1
    readiness: RCAExplanatoryReadinessV1
    robustness: RCARobustnessV1
    terminal_status: RCATerminalStatusV1
    caveats: tuple[RCACaveatCodeV1, ...] = ()
    recommended_next_action: RCANextActionV1
    evidence_refs: tuple[str, ...] = ()


class RCADataQualityIssueV1(RCAAPIModel):
    code: RCADataQualityCodeV1
    severity: Literal["caution", "blocking"]
    source_scope: tuple[RCAFilterV1, ...]
    affects_selected_target: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class RCADataQualityV1(RCAAPIModel):
    status: Literal["pass", "caution", "blocked"]
    issues: tuple[RCADataQualityIssueV1, ...] = ()


class RCAEvidenceV1(RCAAPIModel):
    evidence_ref: str = Field(pattern=r"^EV[1-9][0-9]*$")
    kind: Literal["kpi_movement", "contribution", "data_quality"]
    source_scope: tuple[RCAFilterV1, ...] = ()
    target_scope: tuple[RCAFilterV1, ...] = ()
    dimension: str | None = None
    segment: str | None = None
    baseline_value: float | None = None
    comparison_value: float | None = None
    signed_change: float | None = None
    local_contribution_pct: float | None = None
    global_contribution_pct: float | None = None
    quality_code: RCADataQualityCodeV1 | None = None


class RCAInvestigationResponseV1(RCAAPIModel):
    api_version: Literal["1.0"] = "1.0"
    investigation_id: UUID
    kpi_movement: RCAKPIMovementV1
    investigation_path: tuple[RCAPathStepV1, ...] = ()
    leading_contributor: RCALeadingContributorV1 | None = None
    selected_decomposition: RCATargetDecompositionV1 | None = None
    conclusion: RCAConclusionV1
    data_quality: RCADataQualityV1
    supporting_evidence: tuple[RCAEvidenceV1, ...] = ()


class RCAErrorFieldV1(RCAAPIModel):
    field: str
    code: str


class RCAErrorBodyV1(RCAAPIModel):
    code: Literal[
        "invalid_request",
        "invalid_analysis_definition",
        "dataset_not_found",
        "dataset_unavailable",
        "authentication_required",
        "investigation_failed",
    ]
    message: str
    request_id: str
    fields: tuple[RCAErrorFieldV1, ...] = ()


class RCAErrorResponseV1(RCAAPIModel):
    error: RCAErrorBodyV1

