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

    @model_validator(mode="after")
    def periods_and_dimensions_must_be_distinct(self) -> "SingleLevelInvestigationRequest":
        if self.baseline_period == self.comparison_period:
            raise ValueError("Baseline and comparison periods must differ")
        if len(self.candidate_dimensions) != len(set(self.candidate_dimensions)):
            raise ValueError("Candidate dimensions must be unique")
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


class InvestigationPathNode(RCAContract):
    """One selected scope in the greedy recursive investigation path."""

    node_id: str = Field(pattern=r"^IN\d+$")
    depth: int = Field(ge=0)
    parent_node_id: str | None = Field(default=None, pattern=r"^IN\d+$")
    filter_path: tuple[InvestigationFilter, ...] = Field(default_factory=tuple)
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
