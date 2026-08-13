"""Declarative manager and specialist catalogue for the analytics workforce."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SpecialistProfile:
    name: str
    role: str
    mission: str
    responsibilities: tuple[str, ...]
    required_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    quality_gates: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    escalation_conditions: tuple[str, ...]


@dataclass(frozen=True)
class ManagerProfile:
    name: str
    role: str
    mission: str
    specialists: tuple[str, ...]
    responsibilities: tuple[str, ...]
    quality_gates: tuple[str, ...]
    escalation_conditions: tuple[str, ...]


def _profile(
    name: str,
    role: str,
    mission: str,
    responsibilities: tuple[str, ...],
    required_inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    quality_gates: tuple[str, ...],
    allowed_actions: tuple[str, ...],
    escalation_conditions: tuple[str, ...],
) -> SpecialistProfile:
    return SpecialistProfile(
        name,
        role,
        mission,
        responsibilities,
        required_inputs,
        outputs,
        quality_gates,
        allowed_actions,
        escalation_conditions,
    )


SPECIALISTS = {
    item.name: item
    for item in (
        _profile(
            "BusinessProblemSpecialist", "Business Problem Framing Specialist",
            "Turn an ambiguous request into a decision-focused question without inventing business context.",
            ("Separate the decision from the requested output", "Draft the analytical brief", "Preserve user wording after confirmation"),
            ("rough_prompt", "analysis_objectives"), ("analysis_brief", "proposed_task", "confirmed business_question"),
            ("No invented targets or facts", "The user approves the question in professional mode"),
            ("Structured brief generation", "Checkpoint creation"), ("The decision remains ambiguous", "Required business context is unavailable"),
        ),
        _profile(
            "StakeholderScopeSpecialist", "Stakeholder and Scope Specialist",
            "Make ownership, decision interest, inclusions, exclusions, assumptions, and constraints explicit.",
            ("Review stakeholder coverage", "Review scope boundaries", "Identify missing human context"),
            ("analysis_brief",), ("scope review",), ("Decision, stakeholders, scope, and success criteria are present",),
            ("Read-only contract validation",), ("A material scope or owner is unknown",),
        ),
        _profile(
            "KPISpecialist", "KPI Definition and Measurement Specialist",
            "Ensure success criteria are measurable and denominators, baselines, and targets are never fabricated.",
            ("Review success criteria", "Flag missing metric definitions", "Protect denominator integrity"),
            ("analysis_brief",), ("KPI readiness review",), ("At least one measurable criterion", "Unknown targets remain unknown"),
            ("Read-only measurement review",), ("A requested KPI cannot be defined from supplied context",),
        ),
        _profile(
            "DataIntakeSpecialist", "Data Intake and Provenance Specialist",
            "Verify that every supplied source is accessible, identifiable, and safe to profile.",
            ("Validate source path and format", "Check source identity metadata", "Refuse unsupported inputs"),
            ("file_path", "original_filename", "source_sha256"), ("intake review",),
            ("Source exists", "Supported tabular format", "No source contents are invented"),
            ("Read-only file inspection",), ("Source is missing, unreadable, or unsupported",),
        ),
        _profile(
            "PrepareAgent", "Source Profiling Executor",
            "Create the authoritative structural profile and source-governance checkpoint.",
            ("Profile rows, columns, types, nulls, and duplicates", "Create source register", "Record ROCCC response"),
            ("uploaded source", "session_id"), ("schema_profile", "source_register", "ROCCC record"),
            ("Profile comes from the supplied data", "Governance uncertainty remains visible"),
            ("Read-only profiling", "Audit and checkpoint writes"), ("Profiling fails", "Permission or privacy is unresolved"),
        ),
        _profile(
            "SchemaSpecialist", "Schema and Grain Specialist",
            "Review field types, row grain, candidate keys, and schema usability before transformation.",
            ("Validate profile completeness", "Review grain and candidate keys", "Flag unusable schemas"),
            ("schema_profile", "source_register"), ("schema review",),
            ("Positive row and column counts", "Columns are declared", "Grain uncertainty is explicit"),
            ("Read-only schema validation",), ("No usable fields exist", "The business grain cannot be established"),
        ),
        _profile(
            "DataQualitySpecialist", "Data Quality Diagnostic Specialist",
            "Assess completeness, validity, consistency, uniqueness, and fitness for the confirmed question.",
            ("Review null and duplicate indicators", "Connect defects to analytical risk", "Define non-destructive cautions"),
            ("schema_profile", "business_question"), ("data-quality review",),
            ("Material defects are visible", "No silent repair is recommended"),
            ("Read-only quality assessment",), ("Defects make the requested metric unreliable",),
        ),
        _profile(
            "PrivacyBiasSpecialist", "Privacy, Permission, and Bias Specialist",
            "Prevent analysis or distribution from silently exceeding permission, privacy, or representativeness boundaries.",
            ("Review ROCCC response", "Flag sensitive-field and sampling risk", "Preserve distribution restrictions"),
            ("roccc_answers", "schema_profile"), ("privacy and bias review",),
            ("A source/licence response is recorded", "No permission is inferred"),
            ("Read-only governance review",), ("Permission is denied", "Sensitive data requires a new decision"),
        ),
        _profile(
            "ProcessAgent", "Conservative Transformation Executor",
            "Create a reproducible analysis-ready dataset without silently changing business meaning.",
            ("Normalize safe formatting defects", "Remove exact duplicates under policy", "Write transformation audit"),
            ("source data", "approved source model"), ("cleaned dataset", "cleaning_log", "integrity_checks"),
            ("No silent imputation", "Every row-count change is reconciled"),
            ("Allow-listed deterministic transformations",), ("A requested change alters meaning", "Join expansion is unexplained"),
        ),
        _profile(
            "CleaningSpecialist", "Cleaning Reconciliation Specialist",
            "Independently verify cleaning outcomes, row counts, audit entries, and integrity results.",
            ("Reconcile before and after counts", "Review transformations", "Block failed integrity checks"),
            ("cleaning_log", "final_summary", "integrity_checks", "validation_status"), ("cleaning review",),
            ("Counts reconcile", "No failed critical integrity check"), ("Read-only reconciliation",),
            ("Counts do not reconcile", "Dataset validation failed"),
        ),
        _profile(
            "AnalysisPlannerSpecialist", "Analysis Planning Specialist",
            "Design a coverage-complete plan using only allow-listed, type-compatible operations.",
            ("Map the question to operations", "Declare metrics, dimensions, time fields, and denominators", "Expose limitations"),
            ("business_question", "cleaned dataset", "schema_profile"), ("analysis_plan",),
            ("Every explicit question element is covered", "No model-authored code"),
            ("Structured planning", "Deterministic plan validation"), ("Required fields or denominators do not exist",),
        ),
        _profile(
            "StatisticalAnalysisSpecialist", "Deterministic Statistical Execution Specialist",
            "Execute the approved plan reproducibly and create typed evidence records.",
            ("Run approved calculations", "Disclose populations and methods", "Calibrate confidence"),
            ("approved analysis_plan", "cleaned dataset"), ("evidence", "findings", "analysis_summary"),
            ("Only allow-listed calculations execute", "Every result has method and population"),
            ("Deterministic analysis engine", "Evidence-linked finding generation"), ("Statistical support is insufficient",),
        ),
        _profile(
            "TrendSegmentationSpecialist", "Trend and Segmentation Review Specialist",
            "Check time movement, segment comparison, contribution, and baseline coverage where the objective requires it.",
            ("Review plan-operation coverage", "Check period baselines", "Check segment dimensions"),
            ("analysis_plan", "analysis_objectives"), ("trend and segmentation review",),
            ("Selected objectives are represented or explicitly limited",), ("Read-only plan review",),
            ("A selected objective is omitted from the plan",),
        ),
        _profile(
            "RootCauseAgent", "Root Cause Analytics Specialist",
            "Run typed, falsifiable KPI investigations without upgrading mathematical contribution into unobserved causality.",
            ("Verify metric semantics", "Quantify signed driver contribution", "Reconcile explained and unexplained movement", "Test and falsify competing hypotheses", "Abstain when evidence is unsafe"),
            ("approved plan", "cleaned dataset", "schema_profile"), ("root-cause report", "metric semantics", "evidence-linked findings"),
            ("All references resolve", "Driver changes reconcile", "Causal claims require causal evidence", "Unsafe evidence forces abstention"),
            ("Allow-listed diagnostic calculations", "Typed RCA engine", "Revenue semantic contract"), ("A root cause cannot be identified from observed fields", "Metric policy is ambiguous", "Comparison periods are incomplete"),
        ),
        _profile(
            "EvidenceSpecialist", "Evidence Traceability Specialist",
            "Independently validate citations, populations, methods, confidence, and unanswered questions.",
            ("Resolve finding citations", "Check denominator disclosure", "Review confidence metadata"),
            ("evidence", "findings"), ("evidence review",),
            ("Every citation resolves", "Every finding has implication and confidence"),
            ("Read-only evidence validation",), ("Evidence is empty, orphaned, or incomplete",),
        ),
        _profile(
            "VisualizationSpecialist", "Evidence Visualization Specialist",
            "Create accessible professional charts whose values and encodings come directly from validated evidence.",
            ("Select suitable chart forms", "Render evidence-linked visuals", "Keep source context visible"),
            ("validated evidence", "findings"), ("chart_paths",),
            ("Chart IDs resolve to evidence", "No misleading encoding"), ("Deterministic chart rendering",),
            ("A requested visual would misrepresent the result",),
        ),
        _profile(
            "NarrativeSpecialist", "Analytical Narrative Specialist",
            "Turn approved findings into an answer-first explanation without introducing new claims.",
            ("Review summary completeness", "Preserve caveats", "Connect visuals to findings"),
            ("analysis_summary", "findings", "limitations"), ("narrative review",),
            ("Narrative is non-empty", "No unsupported claim is introduced"), ("Read-only narrative review",),
            ("Narrative changes the meaning of evidence",),
        ),
        _profile(
            "RecommendationSpecialist", "Evidence-Linked Recommendation Specialist",
            "Create bounded actions with owners, timing, monitoring, and explicit uncertainty.",
            ("Prioritize supported actions", "Link actions to findings", "Define monitoring and stop conditions"),
            ("findings", "constraints"), ("recommendations", "monitoring_metrics", "action_package"),
            ("Every action cites a finding", "Unknown impact remains unknown"),
            ("Structured recommendation generation",), ("No evidence supports an action",),
        ),
        _profile(
            "DocumentSpecialist", "Requested Deliverable Assembly Specialist",
            "Create only the user-selected report, presentation, or reproducibility package after release approval.",
            ("Honor output selection", "Assemble editable artifacts", "Preserve methods and revision history"),
            ("approved analytical state", "requested_outputs"), ("registered artifacts",),
            ("No unrequested document", "No new analysis during packaging"), ("Deterministic artifact assembly",),
            ("Publication approval is absent", "An artifact fails verification"),
        ),
        _profile(
            "CalculationReviewer", "Independent Calculation Reviewer",
            "Audit plan-to-result coverage, evidence structure, populations, and method disclosure without changing results.",
            ("Review calculation completeness", "Check operation IDs", "Check population disclosure"),
            ("analysis_plan", "evidence"), ("calculation review decision",),
            ("Every planned operation has evidence", "Every evidence item declares method and population"),
            ("Read-only deterministic audit",), ("A calculation is missing or structurally invalid",),
        ),
        _profile(
            "EvidenceCritic", "Independent Evidence Critic",
            "Challenge unsupported findings and recommendations before they reach a user or artifact.",
            ("Audit citations", "Detect orphan claims", "Check action traceability"),
            ("evidence", "findings", "recommendations"), ("evidence critique decision",),
            ("All claims and actions resolve to approved evidence",), ("Read-only deterministic audit",),
            ("Any claim or action lacks support",),
        ),
        _profile(
            "CausalLanguageReviewer", "Independent Causal-Language Reviewer",
            "Prevent descriptive or associational evidence from being published as causal proof.",
            ("Review claims and implications", "Allow only reconciled contribution language", "Flag causal mechanisms"),
            ("findings", "evidence"), ("causal-language decision",),
            ("No unsupported causal language",), ("Read-only language audit",),
            ("A causal claim lacks an appropriate design",),
        ),
        _profile(
            "PublicationReviewer", "Independent Publication Reviewer",
            "Issue the final release decision only after analytical, governance, narrative, and artifact prerequisites pass.",
            ("Review critical gates", "Review source disclosure", "Review narrative and action readiness"),
            ("complete decision state",), ("publication decision",),
            ("All critical release gates pass",), ("Read-only release audit",),
            ("Any critical publication gate fails",),
        ),
        _profile(
            "MemoryCuratorSpecialist", "Governed Experience Memory Curator",
            "Retrieve and record sanitized recovery lessons without allowing memory to override current evidence or policy.",
            ("Retrieve relevant validated lessons", "Fingerprint sanitized failures", "Record verified recovery"),
            ("scope", "specialist", "stage", "validated outcome"), ("bounded advisory lessons", "memory audit event"),
            ("Candidates are not recalled", "No secrets, prompts, or row data", "Memory is advisory"),
            ("Sanitized memory read and write",), ("Memory is unavailable", "A lesson conflicts with current validation"),
        ),
    )
}


MANAGERS = {
    item.name: item
    for item in (
        ManagerProfile(
            "DiscoveryManager", "Business Discovery Manager",
            "Ensure the analysis starts with the right decision, stakeholders, scope, and measurement criteria.",
            ("BusinessProblemSpecialist", "StakeholderScopeSpecialist", "KPISpecialist"),
            ("Sequence discovery specialists", "Reconcile missing context", "Protect the user's approved intent"),
            ("Decision-ready brief", "Explicit scope", "Measurable success criteria"),
            ("The decision or KPI cannot be defined",),
        ),
        ManagerProfile(
            "DataManager", "Data Readiness and Governance Manager",
            "Supervise intake, profiling, governance, quality diagnosis, conservative cleaning, and reconciliation.",
            ("DataIntakeSpecialist", "PrepareAgent", "SchemaSpecialist", "DataQualitySpecialist", "PrivacyBiasSpecialist", "ProcessAgent", "CleaningSpecialist"),
            ("Sequence data specialists", "Separate diagnosis from transformation", "Block unsafe or unreconciled data work"),
            ("Traceable sources", "Reproducible transformations", "Approved data readiness"),
            ("Permission, grain, or integrity is unresolved",),
        ),
        ManagerProfile(
            "AnalysisManager", "Analytical Evidence Manager",
            "Supervise plan coverage, deterministic execution, diagnostics, and evidence traceability.",
            ("AnalysisPlannerSpecialist", "StatisticalAnalysisSpecialist", "TrendSegmentationSpecialist", "RootCauseAgent", "EvidenceSpecialist"),
            ("Select the correct analytical specialists", "Enforce calculation boundaries", "Return unsupported work for revision"),
            ("Coverage-complete plan", "Reproducible evidence", "Supported findings"),
            ("Safe operations cannot answer the question", "Evidence support is inadequate"),
        ),
        ManagerProfile(
            "DeliveryManager", "Communication and Decision Manager",
            "Supervise faithful visualization, narrative, recommendations, and selected deliverables.",
            ("VisualizationSpecialist", "NarrativeSpecialist", "RecommendationSpecialist", "DocumentSpecialist"),
            ("Route delivery specialists", "Protect claim meaning", "Honor the exact deliverable selection"),
            ("Accurate visuals", "Finding-linked actions", "Only requested artifacts"),
            ("Communication changes evidence meaning", "An output cannot be verified"),
        ),
        ManagerProfile(
            "QualityManager", "Independent Analytical Quality Manager",
            "Independently approve or reject calculations, evidence, causal language, and publication readiness.",
            ("CalculationReviewer", "EvidenceCritic", "CausalLanguageReviewer", "PublicationReviewer", "MemoryCuratorSpecialist"),
            ("Remain independent from producing specialists", "Return exact revision reasons", "Govern recovery memory"),
            ("No unresolved critical review", "Memory cannot bypass validation", "Release requires explicit approval"),
            ("Any critical review fails", "A lesson worsens quality or conflicts with current evidence"),
        ),
    )
}


SPECIALIST_TO_MANAGER = {
    specialist: manager.name
    for manager in MANAGERS.values()
    for specialist in manager.specialists
}


def hierarchy_catalogue() -> dict:
    """Return the complete machine-readable workforce description."""
    return {
        "chief_manager": {
            "name": "AnalyticsManager",
            "role": "Chief Analytics Orchestrator",
            "mission": (
                "Create a stage-aware task plan, delegate only to required domain managers, enforce specialist "
                "contracts, obtain independent quality approval, and retain only governed recovery lessons."
            ),
            "operating_modes": {
                "fast": "Activate the minimum safe specialist team and keep deterministic quality gates.",
                "professional": "Activate the full relevant team with human approval at major stages.",
            },
        },
        "managers": [asdict(profile) for profile in MANAGERS.values()],
        "specialists": [
            asdict(profile) | {"manager": SPECIALIST_TO_MANAGER[profile.name]}
            for profile in SPECIALISTS.values()
        ],
    }
