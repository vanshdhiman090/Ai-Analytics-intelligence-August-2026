"""Strict contracts for deterministic root-cause investigations.

These contracts deliberately separate observed movement, mathematical
contribution, and causal hypotheses.  The analysis engine can therefore fail
closed without asking an LLM to perform arithmetic or decide whether evidence
is sufficient.
"""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EvidenceQuality = Literal["ready", "caution", "insufficient"]
EvidenceType = Literal[
    "descriptive",
    "operational",
    "quasi_experimental",
    "experimental",
]
HypothesisStatus = Literal["supported", "partially_supported", "rejected", "unresolved"]
EvidenceStrength = Literal["high", "medium", "low"]
InvestigationEvidenceStrength = Literal["strong", "moderate", "weak", "insufficient"]
InvestigationHypothesisStatus = Literal["untested", "supported", "weak", "rejected", "unresolved"]
InvestigationOutcome = Literal["strongest_supported_driver", "data_quality_incident", "inconclusive"]
InvestigationStoppingReason = Literal[
    "maximum_depth_reached",
    "no_dimensions_remaining",
    "scoped_data_quality_failure",
    "insufficient_rows",
    "no_aligned_child_contributor",
    "no_material_child_contributor",
    "reconciliation_failure",
    "negligible_parent_movement",
]
HypothesisReasonCode = Literal[
    "kpi_relevance",
    "business_structure",
    "current_scope_relevance",
    "unresolved_uncertainty",
    "potential_explanatory_value",
]
HypothesisProposalSource = Literal["llm", "deterministic_fallback"]
HypothesisProposalRejectionReason = Literal[
    "dimension_not_allowed",
    "dimension_already_tested_in_scope",
    "duplicate_dimension",
    "unsupported_numeric_claim",
    "causal_or_certainty_claim",
    "unsafe_brief_reason",
]
ControllerReasonCode = Literal[
    "highest_planner_priority",
    "resolve_remaining_uncertainty",
    "follow_supported_scope",
    "compare_eligible_dimensions",
    "no_useful_test_remaining",
]
ControllerRejectionReason = Literal[
    "provider_failure",
    "malformed_output",
    "dimension_not_allowed",
    "dimension_already_tested_in_scope",
    "dimension_in_filter_path",
    "unsupported_numeric_claim",
    "causal_or_certainty_claim",
    "unsafe_brief_reason",
    "premature_stop",
    "data_health_blocked",
]
ChallengeType = Literal[
    "competing_driver",
    "leading_segment_remainder",
    "offset_cancellation",
    "data_quality",
    "segment_reliability",
]
ChallengeReasonCode = Literal[
    "compare_tested_decompositions",
    "assess_leading_segment_coverage",
    "assess_opposing_offsets",
    "assess_target_scope_health",
    "assess_segment_reliability",
]
ChallengeProposalSource = Literal["llm", "deterministic_fallback"]
ChallengeProposalRejectionReason = Literal[
    "provider_failure",
    "malformed_output",
    "challenge_not_applicable",
    "duplicate_challenge",
    "reason_code_mismatch",
    "unsupported_numeric_claim",
    "causal_or_certainty_claim",
    "unsafe_brief_reason",
]
VerificationResult = Literal[
    "supports_leading",
    "contradicts_leading",
    "inconclusive",
]
VerificationMateriality = Literal["none", "caution", "material", "blocking"]
VerificationResultCode = Literal[
    "no_material_competitor_detected",
    "competing_driver_caution",
    "material_competing_driver",
    "leading_segment_remainder_low",
    "leading_segment_remainder_caution",
    "leading_segment_remainder_material",
    "offsets_low",
    "offsets_caution",
    "offsets_material",
    "target_scope_quality_safe",
    "target_scope_quality_caution",
    "target_scope_quality_blocking",
    "segment_sample_sufficient",
    "insufficient_segment_sample",
    "segment_structurally_absent_caution",
    "segment_structurally_absent_material",
    "segment_baseline_unavailable",
    "segment_label_not_interpretable",
]
VerificationRobustnessStatus = Literal[
    "not_run",
    "robust_no_material_challenge",
    "robust_with_caveats",
    "weakened",
    "competing_explanations",
    "abstain",
]
ConclusionClaimType = Literal[
    "mathematical_observation",
    "leading_tested_contributor",
    "robust_descriptive_explanation",
    "competing_explanations",
    "inconclusive",
    "data_quality_abstention",
]
ConclusionReadinessStatus = Literal[
    "ready",
    "ready_with_caveats",
    "not_ready_incomplete_testing",
    "not_ready_data_quality",
    "not_ready_reconciliation",
    "not_ready_competing_explanations",
    "not_ready_insufficient_evidence",
    "not_ready_verification_incomplete",
]
ConclusionTerminalCategory = Literal[
    "completed",
    "completed_with_caveats",
    "inconclusive",
    "blocked_by_data_quality",
    "blocked_by_reconciliation",
    "bounded_by_max_depth",
    "no_material_driver",
    "incomplete_testing",
]
ConclusionNextAction = Literal[
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
ConclusionCaveatCode = Literal[
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
    "insufficient_segment_reliability",
]


class RCAContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RCAEvidence(RCAContract):
    evidence_id: str = Field(pattern=r"^E\d+$")
    source_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    quality: EvidenceQuality = "ready"
    evidence_type: EvidenceType = "descriptive"


class RCASemanticDefinition(RCAContract):
    """Minimum semantic definition required for an additive V0 decomposition."""

    metric_name: str = Field(min_length=1)
    metric_column: str = Field(min_length=1)
    time_column: str = Field(min_length=1)
    driver_column: str = Field(min_length=1)
    aggregation: Literal["sum"] = "sum"
    time_grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    unit: str | None = None


class AdditiveKPISemanticDefinition(RCAContract):
    """The intentionally small KPI contract used by the Milestone 1 loop."""

    metric_name: str = Field(min_length=1)
    metric_column: str = Field(min_length=1)
    time_column: str = Field(min_length=1)
    aggregation: Literal["sum"] = "sum"
    time_grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    unit: str | None = None


class IncidentInput(RCAContract):
    metric: str = Field(min_length=1)
    unit: str | None = None
    baseline_period: str = Field(min_length=1)
    comparison_period: str = Field(min_length=1)
    baseline_value: float
    comparison_value: float
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("baseline_value", "comparison_value")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Incident values must be finite")
        return value

    @model_validator(mode="after")
    def periods_must_differ(self) -> "IncidentInput":
        if self.baseline_period == self.comparison_period:
            raise ValueError("Baseline and comparison periods must differ")
        return self


class DataHealthCheck(RCAContract):
    check_id: str = Field(pattern=r"^DH\d+$")
    name: str = Field(min_length=1)
    status: Literal["pass", "caution", "fail", "unknown"]
    blocking: bool = False
    detail: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def only_failures_can_block(self) -> "DataHealthCheck":
        if self.blocking and self.status != "fail":
            raise ValueError("Only a failed data-health check can be blocking")
        return self


class DriverInput(RCAContract):
    driver_id: str = Field(pattern=r"^D\d+$")
    name: str = Field(min_length=1)
    baseline_value: float
    comparison_value: float
    evidence_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("baseline_value", "comparison_value")
    @classmethod
    def values_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Driver values must be finite")
        return value


class FalsificationCheck(RCAContract):
    check_id: str = Field(pattern=r"^FC\d+$")
    description: str = Field(min_length=1)
    outcome: Literal["survived", "falsified", "inconclusive", "not_run"]
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def completed_checks_need_evidence(self) -> "FalsificationCheck":
        if self.outcome in {"survived", "falsified"} and not self.evidence_ids:
            raise ValueError("A conclusive falsification check must cite evidence")
        return self


class HypothesisInput(RCAContract):
    hypothesis_id: str = Field(pattern=r"^H\d+$")
    statement: str = Field(min_length=1)
    supporting_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    contradicting_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    mechanism_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    falsification_checks: tuple[FalsificationCheck, ...] = Field(default_factory=tuple)


class RCAInvestigationRequest(RCAContract):
    contract_version: Literal["0.1"] = "0.1"
    incident: IncidentInput
    evidence: tuple[RCAEvidence, ...] = Field(min_length=1)
    data_health_checks: tuple[DataHealthCheck, ...] = Field(default_factory=tuple)
    drivers: tuple[DriverInput, ...] = Field(default_factory=tuple)
    drivers_form_partition: bool = False
    hypotheses: tuple[HypothesisInput, ...] = Field(default_factory=tuple)
    reconciliation_tolerance_pct: float = Field(default=0.5, ge=0, le=10)

    @model_validator(mode="after")
    def identifiers_and_references_must_be_valid(self) -> "RCAInvestigationRequest":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence IDs must be unique")
        known = set(evidence_ids)

        collections = {
            "driver": [item.driver_id for item in self.drivers],
            "hypothesis": [item.hypothesis_id for item in self.hypotheses],
            "data-health check": [item.check_id for item in self.data_health_checks],
        }
        for label, identifiers in collections.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label.title()} IDs must be unique")

        references: list[tuple[str, tuple[str, ...]]] = [
            ("incident", self.incident.evidence_ids),
            *((f"driver {item.driver_id}", item.evidence_ids) for item in self.drivers),
            *((f"data-health check {item.check_id}", item.evidence_ids) for item in self.data_health_checks),
        ]
        for hypothesis in self.hypotheses:
            references.extend(
                (
                    (f"hypothesis {hypothesis.hypothesis_id} support", hypothesis.supporting_evidence_ids),
                    (f"hypothesis {hypothesis.hypothesis_id} contradiction", hypothesis.contradicting_evidence_ids),
                    (f"hypothesis {hypothesis.hypothesis_id} mechanism", hypothesis.mechanism_evidence_ids),
                )
            )
            references.extend(
                (f"falsification check {check.check_id}", check.evidence_ids)
                for check in hypothesis.falsification_checks
            )
        for label, ids in references:
            unknown = sorted(set(ids) - known)
            if unknown:
                raise ValueError(f"{label} cites unknown evidence: {unknown}")
        return self


class IncidentAssessment(RCAContract):
    metric: str
    unit: str | None
    baseline_period: str
    comparison_period: str
    baseline_value: float
    comparison_value: float
    absolute_change: float
    percent_change: float | None
    direction: Literal["increase", "decrease", "no_change"]
    evidence_ids: tuple[str, ...]


class DataHealthAssessment(RCAContract):
    status: Literal["pass", "caution", "fail", "unknown"]
    blocking_failures: tuple[str, ...] = Field(default_factory=tuple)
    cautions: tuple[str, ...] = Field(default_factory=tuple)
    evidence_strength: EvidenceStrength


class DriverContribution(RCAContract):
    driver_id: str
    name: str
    baseline_value: float
    comparison_value: float
    absolute_change: float
    contribution_to_total_change_pct: float | None
    direction: Literal["with_incident", "against_incident", "neutral"]
    evidence_ids: tuple[str, ...]
    evidence_strength: EvidenceStrength


class ReconciliationAssessment(RCAContract):
    reconcilable: bool
    incident_change: float
    explained_change: float | None
    unexplained_change: float | None
    explained_pct: float | None
    unexplained_pct: float | None
    residual_within_tolerance: bool | None
    note: str


class HypothesisAssessment(RCAContract):
    hypothesis_id: str
    statement: str
    status: HypothesisStatus
    evidence_strength: EvidenceStrength
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    mechanism_evidence_ids: tuple[str, ...]
    falsification_outcomes: tuple[str, ...]
    causal_evidence_present: bool
    rationale: str


class RCAConclusion(RCAContract):
    determination: Literal[
        "causal_root_cause_supported",
        "mathematical_driver_identified",
        "inconclusive",
    ]
    statement: str
    primary_driver_id: str | None = None
    leading_hypothesis_id: str | None = None
    causal_claim_allowed: bool = False
    evidence_strength: EvidenceStrength
    abstention_reason: str | None = None


class RCAInvestigationReport(RCAContract):
    contract_version: Literal["0.1"] = "0.1"
    incident: IncidentAssessment
    data_health: DataHealthAssessment
    drivers: tuple[DriverContribution, ...]
    reconciliation: ReconciliationAssessment
    hypotheses: tuple[HypothesisAssessment, ...]
    conclusion: RCAConclusion
    next_investigations: tuple[str, ...]
    limitations: tuple[str, ...]
    analysis_trail: tuple[str, ...]


# Milestone 1 deliberately models only a single, deterministic layer of
# investigation.  These contracts do not claim causality and do not introduce
# recursive drill-down or LLM-generated hypotheses.
class SingleLevelInvestigationRequest(RCAContract):
    investigation_id: str = Field(min_length=1, max_length=128)
    goal: str = Field(min_length=1, max_length=500)
    kpi: AdditiveKPISemanticDefinition
    baseline_period: str = Field(min_length=1)
    comparison_period: str = Field(min_length=1)
    candidate_dimensions: tuple[str, ...] = Field(min_length=1, max_length=12)
    material_contribution_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    comparison_coverage_ratio: float = Field(default=0.8, gt=0.0, le=1.0)
    maximum_current_metric_null_pct: float = Field(default=0.2, ge=0.0, le=1.0)
    # Depth 0 is the global incident; depth 1 is the first selected segment.
    # The default preserves the exact Milestone 1 single-level behavior.
    maximum_depth: int = Field(default=1, ge=1, le=8)
    # A deterministic safety policy only; this is not statistical confidence.
    minimum_rows_per_period_for_drill_down: int = Field(default=5, ge=1)
    negligible_parent_movement_tolerance: float = Field(default=1e-9, ge=0.0)
    hypothesis_planning_enabled: bool = False
    evidence_driven_control_enabled: bool = False
    self_falsification_enabled: bool = False
    conclusion_compilation_enabled: bool = False

    @model_validator(mode="after")
    def periods_and_dimensions_must_be_distinct(self) -> "SingleLevelInvestigationRequest":
        if self.baseline_period == self.comparison_period:
            raise ValueError("Baseline and comparison periods must differ")
        if len(self.candidate_dimensions) != len(set(self.candidate_dimensions)):
            raise ValueError("Candidate dimensions must be unique")
        if self.self_falsification_enabled and not self.evidence_driven_control_enabled:
            raise ValueError(
                "Self-falsification requires the evidence-driven controller"
            )
        return self


class InvestigationHealthCheck(RCAContract):
    check_id: str = Field(pattern=r"^IQ\d+$")
    name: str = Field(min_length=1)
    status: Literal["pass", "caution", "fail"]
    blocking: bool = False
    detail: str = Field(min_length=1)
    evidence_id: str = Field(pattern=r"^IE\d+$")


class InvestigationEvidence(RCAContract):
    evidence_id: str = Field(pattern=r"^IE\d+$")
    test_id: str | None = Field(default=None, pattern=r"^IT\d+$")
    kind: Literal["incident", "data_health", "dimension_contribution"]
    description: str = Field(min_length=1)
    dimension: str | None = None
    segment: str | None = None
    values: dict[str, float | int | str | None] = Field(default_factory=dict)


class SegmentContribution(RCAContract):
    dimension: str
    segment: str
    baseline_value: float
    comparison_value: float
    signed_change: float
    contribution_to_net_change_pct: float | None
    direction: Literal["with_incident", "positive_offset", "negative_pressure", "neutral"]
    # Raw row presence per period, captured before the notna() filter and the
    # unstack(fill_value=0) pivot collapse genuine absence, a null-derived
    # value, and a genuine zero into the same 0. row_count == 0 means the
    # segment had no raw rows in that period at all; null_metric_row_count
    # == row_count (with row_count > 0) means every raw row existed but had
    # no usable metric value. Data capture only -- not yet read anywhere.
    baseline_row_count: int = Field(default=0, ge=0)
    comparison_row_count: int = Field(default=0, ge=0)
    baseline_null_metric_row_count: int = Field(default=0, ge=0)
    comparison_null_metric_row_count: int = Field(default=0, ge=0)


class DimensionContributionTest(RCAContract):
    test_id: str = Field(pattern=r"^IT\d+$")
    dimension: str
    status: Literal["completed", "unresolved"]
    evidence_id: str = Field(pattern=r"^IE\d+$")
    segment_contributions: tuple[SegmentContribution, ...] = Field(default_factory=tuple)
    negative_pressure: float
    positive_offset: float
    net_dimension_change: float
    reconciles_to_kpi_change: bool


class InvestigationHypothesis(RCAContract):
    hypothesis_id: str = Field(pattern=r"^IH\d+$")
    dimension: str
    statement: str
    status: InvestigationHypothesisStatus = "untested"
    leading_segment: str | None = None
    signed_contribution: float | None = None
    contribution_to_net_change_pct: float | None = None
    evidence_strength: InvestigationEvidenceStrength = "insufficient"
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    rationale: str = "Not tested."


class HypothesisProposal(RCAContract):
    """The deliberately small model-authored proposal surface."""

    target_dimension: str = Field(min_length=1, max_length=128)
    reason_code: HypothesisReasonCode
    brief_reason: str | None = Field(default=None, max_length=180)


class HypothesisProposalSet(RCAContract):
    proposals: tuple[HypothesisProposal, ...] = Field(min_length=1, max_length=12)


class RejectedHypothesisProposal(RCAContract):
    target_dimension: str = Field(min_length=1, max_length=128)
    rejection_reason: HypothesisProposalRejectionReason


class PlannedHypothesis(RCAContract):
    hypothesis_id: str = Field(pattern=r"^HP\d+$")
    target_dimension: str = Field(min_length=1)
    priority: int = Field(ge=1)
    statement: str = Field(min_length=1)
    reason_code: HypothesisReasonCode
    brief_reason: str | None = None
    evidence_needed: Literal["signed_segment_contribution"] = "signed_segment_contribution"
    source: HypothesisProposalSource
    status: InvestigationHypothesisStatus = "untested"
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)


class HypothesisPlanningRecord(RCAContract):
    planning_id: str = Field(pattern=r"^IP\d+$")
    planner_version: Literal["hypothesis-planner-v1"] = "hypothesis-planner-v1"
    filter_path: tuple["InvestigationFilter", ...] = Field(default_factory=tuple)
    allowed_dimensions: tuple[str, ...]
    validated_proposals: tuple[PlannedHypothesis, ...]
    rejected_proposals: tuple[RejectedHypothesisProposal, ...] = Field(default_factory=tuple)
    fallback_reason: Literal["provider_failure", "unusable_output", "no_valid_proposals"] | None = None
    planner_mode: Literal["llm", "deterministic_fallback", "llm_with_fallback"]


class NextTestActionProposal(RCAContract):
    action: Literal["test_dimension", "stop"]
    target_dimension: str | None = Field(default=None, max_length=128)
    reason_code: ControllerReasonCode
    brief_reason: str | None = Field(default=None, max_length=180)

    @model_validator(mode="after")
    def target_matches_action(self) -> "NextTestActionProposal":
        if self.action == "test_dimension" and not self.target_dimension:
            raise ValueError("test_dimension requires target_dimension")
        if self.action == "stop" and self.target_dimension is not None:
            raise ValueError("stop must not include target_dimension")
        return self


class InvestigationFilter(RCAContract):
    dimension: str = Field(min_length=1)
    segment: str = Field(min_length=1)


class InvestigationIteration(RCAContract):
    iteration_id: str = Field(pattern=r"^II\d+$")
    scope_node_id: str = Field(pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
    available_dimensions: tuple[str, ...]
    tested_dimensions_before: tuple[str, ...] = Field(default_factory=tuple)
    known_test_ids: tuple[str, ...] = Field(default_factory=tuple)
    requested_action: Literal["test_dimension", "stop"] | None = None
    requested_dimension: str | None = None
    executed_action: Literal["test_dimension", "stop"]
    executed_dimension: str | None = None
    decision_source: Literal["llm", "deterministic_fallback"]
    validation_status: Literal["accepted", "rejected"]
    rejection_reason: ControllerRejectionReason | None = None
    controller_reason_code: ControllerReasonCode | None = None
    fallback_used: bool = False
    test_id: str | None = Field(default=None, pattern=r"^IT\d+$")
    evidence_id: str | None = Field(default=None, pattern=r"^IE\d+$")
    resulting_hypothesis_status: InvestigationHypothesisStatus | None = None
    iteration_outcome: Literal["test_executed", "stop_accepted"]
    continue_reason: str | None = None
    terminal_reason: str | None = None


class VerificationPolicyV1(RCAContract):
    """Versioned engineering heuristics, not calibrated probabilities."""

    verification_policy_version: Literal["verification-policy-v1"] = (
        "verification-policy-v1"
    )
    competing_driver_caution_ratio: float = Field(default=0.60, ge=0.0)
    competing_driver_material_ratio: float = Field(default=0.80, ge=0.0)
    leading_segment_remainder_caution_ratio: float = Field(default=0.20, ge=0.0)
    leading_segment_remainder_material_ratio: float = Field(default=0.50, ge=0.0)
    offset_caution_ratio: float = Field(default=0.10, ge=0.0)
    offset_material_ratio: float = Field(default=0.20, ge=0.0)
    # Below this many raw rows in either period, the target segment's own
    # baseline/comparison value is not a reliable estimate. Matches
    # SingleLevelInvestigationRequest.minimum_rows_per_period_for_drill_down
    # (also 5) -- the only other row-count threshold in this codebase --
    # rather than inventing an unrelated number.
    minimum_segment_row_count: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def caution_thresholds_precede_material_thresholds(self) -> "VerificationPolicyV1":
        if self.competing_driver_caution_ratio >= self.competing_driver_material_ratio:
            raise ValueError("Competing-driver caution must be below material")
        if (
            self.leading_segment_remainder_caution_ratio
            >= self.leading_segment_remainder_material_ratio
        ):
            raise ValueError("Remainder caution must be below material")
        if self.offset_caution_ratio >= self.offset_material_ratio:
            raise ValueError("Offset caution must be below material")
        return self


class VerificationTarget(RCAContract):
    scope_node_id: str = Field(pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
    target_dimension: str = Field(min_length=1)
    target_segment: str = Field(min_length=1)
    source_test_ids: tuple[str, ...] = Field(min_length=1)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)


class ChallengeProposal(RCAContract):
    challenge_type: ChallengeType
    reason_code: ChallengeReasonCode
    brief_reason: str | None = Field(default=None, max_length=180)


class ChallengeProposalSet(RCAContract):
    proposals: tuple[ChallengeProposal, ...] = Field(min_length=1, max_length=4)


class RejectedChallengeProposal(RCAContract):
    challenge_type: str = Field(min_length=1, max_length=64)
    rejection_reason: ChallengeProposalRejectionReason


class PlannedChallenge(RCAContract):
    challenge_id: str = Field(pattern=r"^VC\d+$")
    challenge_type: ChallengeType
    reason_code: ChallengeReasonCode
    brief_reason: str | None = None
    source: ChallengeProposalSource


class ChallengePlanningRecord(RCAContract):
    planning_id: str = Field(pattern=r"^VP\d+$")
    planner_version: Literal["challenge-planner-v1"] = "challenge-planner-v1"
    verification_policy_version: Literal["verification-policy-v1"] = (
        "verification-policy-v1"
    )
    target: VerificationTarget
    applicable_challenges: tuple[ChallengeType, ...]
    validated_challenges: tuple[PlannedChallenge, ...]
    rejected_proposals: tuple[RejectedChallengeProposal, ...] = Field(
        default_factory=tuple
    )
    fallback_reason: Literal[
        "provider_failure",
        "malformed_output",
        "no_valid_proposals",
        "omitted_required_challenges",
    ] | None = None
    planner_mode: Literal[
        "llm",
        "deterministic_fallback",
        "llm_with_fallback",
    ]


class VerificationRecord(RCAContract):
    verification_id: str = Field(pattern=r"^IV\d+$")
    verification_policy_version: Literal["verification-policy-v1"] = (
        "verification-policy-v1"
    )
    challenge_type: ChallengeType
    target: VerificationTarget
    source_test_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    result: VerificationResult
    materiality: VerificationMateriality
    result_code: VerificationResultCode
    metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)


class InvestigationPathNode(RCAContract):
    """One selected scope in the greedy recursive investigation path."""

    node_id: str = Field(pattern=r"^IN\d+$")
    depth: int = Field(ge=0)
    parent_node_id: str | None = Field(default=None, pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
    # Explicit ID link (not positional) to the HypothesisPlanningRecord whose
    # planning, in the PARENT scope, produced this node's selected_dimension.
    # None on the root node, which has no selected_dimension to explain.
    planning_id: str | None = Field(default=None, pattern=r"^IP\d+$")
    selected_dimension: str | None = None
    selected_segment: str | None = None
    parent_kpi_movement: float | None = None
    segment_movement: float | None = None
    local_contribution_pct: float | None = None
    global_contribution_pct: float | None = None
    remaining_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    tested_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    test_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    data_health: tuple[InvestigationHealthCheck, ...] = Field(default_factory=tuple)
    evidence_strength: InvestigationEvidenceStrength = "insufficient"
    stopping_reason: InvestigationStoppingReason | None = None


class ConclusionTargetScope(RCAContract):
    """Exact selected scope plus the parent scope that produced its evidence."""

    source_scope_node_id: str = Field(pattern=r"^IN\d+$")
    target_path_node_id: str | None = Field(default=None, pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
    target_dimension: str | None = None
    target_segment: str | None = None


class ConclusionReadinessChecks(RCAContract):
    """Readiness for a stronger explanatory claim, not for returning a response."""

    valid_kpi_movement: bool
    exact_scope_data_quality_safe: bool
    required_dimensions_tested: bool
    reconciliation_passed: bool
    leader_resolved: bool
    evidence_sufficient: bool
    verification_required: bool
    verification_completed: bool
    verification_applies_to_target: bool
    execution_complete: bool
    lineage_validated: bool


class ConclusionStopDetail(RCAContract):
    scope_node_id: str = Field(pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
    stopping_reason: InvestigationStoppingReason


class InvestigationConclusion(RCAContract):
    conclusion_id: str = Field(pattern=r"^ICL\d+$")
    compiler_version: Literal["conclusion-compiler-v1"] = "conclusion-compiler-v1"
    investigation_id: str = Field(min_length=1)
    claim_type: ConclusionClaimType
    readiness_status: ConclusionReadinessStatus
    terminal_category: ConclusionTerminalCategory
    kpi: AdditiveKPISemanticDefinition
    baseline_period: str = Field(min_length=1)
    comparison_period: str = Field(min_length=1)
    target_scope: ConclusionTargetScope
    conclusion_path_node_ids: tuple[str, ...] = Field(default_factory=tuple)
    leading_dimension: str | None = None
    leading_segment: str | None = None
    signed_contribution: float | None = None
    contribution_to_net_change_pct: float | None = None
    evidence_strength: InvestigationEvidenceStrength
    robustness_status: VerificationRobustnessStatus
    verification_target_scope_node_id: str | None = Field(
        default=None, pattern=r"^IN\d+$"
    )
    supporting_test_ids: tuple[str, ...] = Field(default_factory=tuple)
    supporting_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    verification_ids: tuple[str, ...] = Field(default_factory=tuple)
    caveat_codes: tuple[ConclusionCaveatCode, ...] = Field(default_factory=tuple)
    source_stopping_reason: str = Field(min_length=1)
    low_level_stops: tuple[ConclusionStopDetail, ...] = Field(default_factory=tuple)
    readiness_checks: ConclusionReadinessChecks
    recommended_next_action: ConclusionNextAction

    @model_validator(mode="after")
    def epistemic_compatibility_matrix(self) -> "InvestigationConclusion":
        checks = self.readiness_checks
        ready = self.readiness_status in {"ready", "ready_with_caveats"}
        strongest = self.claim_type in {
            "leading_tested_contributor",
            "robust_descriptive_explanation",
        }
        if ready and not all(
            (
                checks.valid_kpi_movement,
                checks.exact_scope_data_quality_safe,
                checks.required_dimensions_tested,
                checks.reconciliation_passed,
                checks.leader_resolved,
                checks.evidence_sufficient,
                checks.execution_complete,
                checks.lineage_validated,
            )
        ):
            raise ValueError("Ready explanatory claims require every deterministic gate")
        if strongest and not ready:
            raise ValueError("Strongest-contributor claims require explanatory readiness")
        if strongest and (not checks.required_dimensions_tested or not checks.reconciliation_passed):
            raise ValueError("Incomplete or unreconciled analysis forbids strongest claims")
        if strongest and self.evidence_strength not in {"strong", "moderate"}:
            raise ValueError("Weak evidence cannot support a strongest-contributor claim")
        if self.claim_type == "robust_descriptive_explanation":
            if self.robustness_status not in {
                "robust_no_material_challenge",
                "robust_with_caveats",
            }:
                raise ValueError("Robust claim is incompatible with robustness status")
            if not (
                checks.verification_required
                and checks.verification_completed
                and checks.verification_applies_to_target
            ):
                raise ValueError("Robust claim requires completed target-scope verification")
        if checks.verification_required and not checks.verification_completed and self.claim_type == "robust_descriptive_explanation":
            raise ValueError("Requested but incomplete verification forbids robust claims")
        if self.robustness_status == "competing_explanations" and self.claim_type != "competing_explanations":
            raise ValueError("Competing robustness requires a competing-explanations claim")
        if self.claim_type == "competing_explanations":
            if self.robustness_status != "competing_explanations" or self.readiness_status != "not_ready_competing_explanations":
                raise ValueError("Competing claim requires matching robustness and readiness")
        if self.claim_type == "data_quality_abstention":
            if checks.exact_scope_data_quality_safe:
                raise ValueError("Data-quality abstention requires a blocking target-scope issue")
            if self.readiness_status != "not_ready_data_quality" or self.terminal_category != "blocked_by_data_quality":
                raise ValueError("Data-quality abstention requires matching readiness and terminal status")
        if not checks.exact_scope_data_quality_safe and self.claim_type != "data_quality_abstention":
            raise ValueError("Unsafe exact-target data requires a data-quality abstention")
        if self.robustness_status in {
            "robust_no_material_challenge",
            "robust_with_caveats",
        } and not checks.verification_completed:
            raise ValueError("A robust status requires completed verification records")
        if self.readiness_status == "not_ready_data_quality" and checks.exact_scope_data_quality_safe:
            raise ValueError("Data-quality not-ready status requires an unsafe exact scope")
        if self.readiness_status == "not_ready_reconciliation" and checks.reconciliation_passed:
            raise ValueError("Reconciliation not-ready status requires reconciliation failure")
        if self.readiness_status == "not_ready_incomplete_testing" and checks.required_dimensions_tested:
            raise ValueError("Incomplete-testing status requires missing required tests")
        if self.readiness_status == "not_ready_verification_incomplete" and not (
            checks.verification_required and not checks.verification_completed
        ):
            raise ValueError("Verification-incomplete status requires unfinished requested verification")
        if self.readiness_status == "not_ready_insufficient_evidence" and checks.evidence_sufficient:
            raise ValueError("Insufficient-evidence status requires insufficient evidence")
        if self.target_scope.target_path_node_id is not None:
            if not self.conclusion_path_node_ids or self.conclusion_path_node_ids[-1] != self.target_scope.target_path_node_id:
                raise ValueError("Conclusion path must terminate at the exact target node")
        if len(self.conclusion_path_node_ids) != len(set(self.conclusion_path_node_ids)):
            raise ValueError("Conclusion path node IDs must be unique")
        if self.target_scope.filter_path and self.target_scope.target_dimension:
            last = self.target_scope.filter_path[-1]
            if last.dimension != self.target_scope.target_dimension or last.segment != self.target_scope.target_segment:
                raise ValueError("Target identity must match the final filter-path step")
        if self.claim_type not in {"inconclusive", "data_quality_abstention"} and not self.supporting_evidence_ids:
            raise ValueError("A positive bounded claim requires supporting evidence")
        return self


class InvestigationState(RCAContract):
    investigation_id: str
    goal: str
    kpi: AdditiveKPISemanticDefinition
    baseline_period: str
    comparison_period: str
    candidate_dimensions: tuple[str, ...]
    outcome: InvestigationOutcome
    baseline_value: float | None = None
    comparison_value: float | None = None
    net_kpi_movement: float | None = None
    data_health: tuple[InvestigationHealthCheck, ...] = Field(default_factory=tuple)
    hypotheses: tuple[InvestigationHypothesis, ...] = Field(default_factory=tuple)
    tests_executed: tuple[DimensionContributionTest, ...] = Field(default_factory=tuple)
    evidence: tuple[InvestigationEvidence, ...] = Field(default_factory=tuple)
    leading_dimension: str | None = None
    leading_segment: str | None = None
    leading_signed_contribution: float | None = None
    leading_contribution_to_net_change_pct: float | None = None
    downward_pressure: float | None = None
    positive_offset: float | None = None
    explained_movement: float | None = None
    unexplained_movement: float | None = None
    evidence_strength: InvestigationEvidenceStrength = "insufficient"
    stopping_reason: str
    # Empty in the legacy/default Milestone 1 route. Recursive runs contain
    # depth 0 plus the one greedy selected path.
    investigation_path: tuple[InvestigationPathNode, ...] = Field(default_factory=tuple)
    hypothesis_planning_records: tuple[HypothesisPlanningRecord, ...] = Field(default_factory=tuple)
    investigation_iterations: tuple[InvestigationIteration, ...] = Field(default_factory=tuple)
    verification_policy_version: Literal["verification-policy-v1"] | None = None
    challenge_planning_record: ChallengePlanningRecord | None = None
    verification_records: tuple[VerificationRecord, ...] = Field(default_factory=tuple)
    supporting_verification_ids: tuple[str, ...] = Field(default_factory=tuple)
    contradicting_verification_ids: tuple[str, ...] = Field(default_factory=tuple)
    unresolved_verification_ids: tuple[str, ...] = Field(default_factory=tuple)
    verification_status: VerificationRobustnessStatus = "not_run"
    verification_evidence_strength: InvestigationEvidenceStrength = "insufficient"
    verification_rationale: str | None = None
    final_conclusion: InvestigationConclusion | None = None
