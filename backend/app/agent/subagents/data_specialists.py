"""Deterministic, narrowly scoped review specialists for the Data Manager.

These specialists inspect artifacts already produced by the workflow.  They do
not load data, transform records, call models, or persist state.  Every return
value is an additive review payload that a manager can merge into workflow
state without replacing the underlying evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar

from app.agent.subagents.base import BaseSubAgent


class DataSpecialistContractError(ValueError):
    """Raised when supplied workflow evidence is materially invalid."""


def _mapping(state: Mapping[str, Any], key: str, specialist: str) -> Mapping[str, Any]:
    value = state.get(key)
    if not isinstance(value, Mapping):
        raise DataSpecialistContractError(
            f"{specialist} requires '{key}' to be a structured mapping; "
            f"received {type(value).__name__}."
        )
    return value


def _records(
    state: Mapping[str, Any], key: str, specialist: str, *, required: bool = False
) -> list[Mapping[str, Any]]:
    value = state.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise DataSpecialistContractError(
            f"{specialist} requires '{key}' to be a list of structured records."
        )
    return value


def _count(value: Any, field: str, specialist: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DataSpecialistContractError(
            f"{specialist} requires '{field}' to be a non-negative integer."
        )
    return value


def _review(
    specialist: type[BaseSubAgent],
    *,
    status: str,
    checks: list[dict[str, Any]],
    escalation_reasons: list[str],
    **facts: Any,
) -> dict[str, Any]:
    return {
        "specialist": specialist.name,
        "role": specialist.domain_role,
        "status": status,
        "checks": checks,
        "escalation_required": bool(escalation_reasons),
        "escalation_reasons": escalation_reasons,
        **facts,
    }


class _DataReviewSpecialist(BaseSubAgent):
    """Common professional contract metadata for deterministic reviewers."""

    mission: ClassVar[str]
    responsibilities: ClassVar[tuple[str, ...]]
    required_inputs: ClassVar[tuple[str, ...]]
    outputs: ClassVar[tuple[str, ...]]
    quality_gates: ClassVar[tuple[str, ...]]
    allowed_actions: ClassVar[tuple[str, ...]] = (
        "Read workflow state",
        "Perform deterministic contract checks",
        "Return an additive review payload",
    )
    escalation_conditions: ClassVar[tuple[str, ...]]

    @classmethod
    def professional_metadata(cls) -> dict[str, Any]:
        """Return JSON-ready role metadata for catalogues and manager briefs."""
        return {
            "name": cls.name,
            "role": cls.domain_role,
            "description": cls.description,
            "mission": cls.mission,
            "responsibilities": list(cls.responsibilities),
            "required_inputs": list(cls.required_inputs),
            "outputs": list(cls.outputs),
            "quality_gates": list(cls.quality_gates),
            "allowed_actions": list(cls.allowed_actions),
            "escalation_conditions": list(cls.escalation_conditions),
        }


class DataIntakeSpecialist(_DataReviewSpecialist):
    """Review source identity and intake traceability without reading the data."""

    name = "DataIntakeSpecialist"
    domain_role = "Data Intake & Source Traceability Specialist"
    description = "Validates that supplied sources are identifiable and auditable before profiling."
    mission = "Establish an evidence-backed intake record without inferring provenance or permission."
    responsibilities = (
        "Verify that each supplied source has a stable identity",
        "Check declared formats and source-register uniqueness",
        "Surface missing provenance for manager escalation",
    )
    required_inputs = ("file_path or source_register",)
    outputs = ("data_intake_review",)
    quality_gates = (
        "At least one source is declared",
        "Source identifiers are unique",
        "No provenance or permission is invented",
    )
    escalation_conditions = (
        "A source has no filename or path",
        "Format or provenance is not declared",
    )

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        if not isinstance(state, Mapping):
            raise DataSpecialistContractError("DataIntakeSpecialist requires workflow state as a mapping.")

        sources = _records(state, "source_register", self.name)
        file_path = str(state.get("file_path") or "").strip()
        if not sources and not file_path:
            raise DataSpecialistContractError(
                "DataIntakeSpecialist requires at least one declared source in "
                "'source_register' or a non-empty 'file_path'."
            )

        declared: list[dict[str, str]] = []
        missing_identity: list[str] = []
        missing_format: list[str] = []
        identifiers: list[str] = []
        if sources:
            for index, source in enumerate(sources, 1):
                identifier = str(source.get("source_id") or "").strip()
                filename = str(source.get("filename") or "").strip()
                source_path = str(source.get("file_path") or "").strip()
                label = identifier or filename or f"source #{index}"
                if not filename and not source_path:
                    missing_identity.append(label)
                if identifier:
                    identifiers.append(identifier)
                declared_format = str(source.get("format") or "").strip().upper()
                if not declared_format:
                    suffix = Path(filename or source_path).suffix.lstrip(".").upper()
                    declared_format = suffix
                if not declared_format:
                    missing_format.append(label)
                declared.append(
                    {
                        "source_id": identifier,
                        "filename": filename or Path(source_path).name,
                        "declared_format": declared_format,
                    }
                )
        else:
            source = Path(file_path)
            declared.append(
                {
                    "source_id": "",
                    "filename": str(state.get("original_filename") or source.name),
                    "declared_format": source.suffix.lstrip(".").upper(),
                }
            )

        duplicates = sorted(name for name, count in Counter(identifiers).items() if count > 1)
        if duplicates:
            raise DataSpecialistContractError(
                "DataIntakeSpecialist found duplicate source identifiers: " + ", ".join(duplicates)
            )
        if missing_identity:
            raise DataSpecialistContractError(
                "DataIntakeSpecialist found sources without a filename or path: "
                + ", ".join(missing_identity)
            )

        escalations = []
        if missing_format:
            escalations.append("Confirm the format for: " + ", ".join(missing_format))
        if not state.get("source_sha256") and any(not source.get("sha256") for source in sources):
            escalations.append("Record a source checksum for reproducible identity.")
        review = _review(
            type(self),
            status="review_required" if escalations else "ready",
            checks=[
                {"check": "source_declared", "status": "pass", "observed": len(declared)},
                {"check": "unique_source_ids", "status": "pass", "duplicates": []},
                {
                    "check": "format_declared",
                    "status": "warning" if missing_format else "pass",
                    "missing": missing_format,
                },
            ],
            escalation_reasons=escalations,
            source_count=len(declared),
            sources=declared,
            provenance_assertion="Not independently verified",
        )
        return {"data_intake_review": review}


class SchemaSpecialist(_DataReviewSpecialist):
    """Validate schema-profile structure and surface analytical constraints."""

    name = "SchemaSpecialist"
    domain_role = "Schema & Analytical Grain Specialist"
    description = "Reviews profile consistency, field usability, and candidate identifiers."
    mission = "Ensure downstream work receives a coherent schema without assigning unverified business meaning."
    responsibilities = (
        "Reconcile declared row and column counts",
        "Identify structurally unusable and constant fields",
        "Surface candidate keys as hypotheses, never confirmed keys",
    )
    required_inputs = ("schema_profile",)
    outputs = ("schema_review",)
    quality_gates = (
        "Profile counts are valid and internally consistent",
        "Every column profile is structured",
        "Business grain remains explicitly unverified unless supplied by a human",
    )
    escalation_conditions = (
        "The dataset has no usable columns",
        "Profile counts contradict field-level evidence",
        "All fields are structurally unusable",
    )

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        profile = _mapping(state, "schema_profile", self.name)
        rows = _count(profile.get("row_count"), "schema_profile.row_count", self.name)
        columns_count = _count(
            profile.get("column_count"), "schema_profile.column_count", self.name
        )
        columns = profile.get("columns")
        if not isinstance(columns, Mapping) or any(
            not isinstance(item, Mapping) for item in columns.values()
        ):
            raise DataSpecialistContractError(
                "SchemaSpecialist requires 'schema_profile.columns' to map column names to profiles."
            )
        if columns_count != len(columns):
            raise DataSpecialistContractError(
                "SchemaSpecialist found a column-count mismatch: "
                f"profile declares {columns_count}, but {len(columns)} column profiles are present."
            )
        if columns_count == 0:
            raise DataSpecialistContractError("SchemaSpecialist cannot approve a dataset with zero columns.")

        all_null = sorted(str(item) for item in profile.get("all_null_columns", []))
        constants = sorted(str(item) for item in profile.get("constant_columns", []))
        unknown_types = sorted(
            str(name)
            for name, item in columns.items()
            if str(item.get("semantic_type") or "unknown").lower() == "unknown"
        )
        candidate_keys = sorted(
            str(name)
            for name, item in columns.items()
            if rows > 0
            and item.get("null_count") == 0
            and item.get("unique_count") == rows
            and str(name).lower().endswith(("id", "_key"))
        )
        unusable = set(all_null)
        if len(unusable) == columns_count:
            raise DataSpecialistContractError(
                "SchemaSpecialist found that every declared column is all-null and unusable."
            )

        escalations = []
        if rows == 0:
            escalations.append("The supplied dataset has zero observed rows.")
        if all_null:
            escalations.append("Exclude all-null fields from analytical plans: " + ", ".join(all_null))
        if unknown_types:
            escalations.append("Confirm semantic types for: " + ", ".join(unknown_types))
        review = _review(
            type(self),
            status="review_required" if escalations else "ready",
            checks=[
                {"check": "profile_count_reconciliation", "status": "pass"},
                {
                    "check": "usable_columns",
                    "status": "warning" if all_null else "pass",
                    "all_null_columns": all_null,
                },
                {
                    "check": "semantic_types",
                    "status": "warning" if unknown_types else "pass",
                    "unknown_columns": unknown_types,
                },
            ],
            escalation_reasons=escalations,
            row_count=rows,
            column_count=columns_count,
            constant_columns=constants,
            candidate_keys=candidate_keys,
            candidate_key_caveat="Candidates require business-owner confirmation before joins.",
            grain_status="Unverified unless explicitly confirmed in the source register.",
        )
        return {"schema_review": review}


class DataQualitySpecialist(_DataReviewSpecialist):
    """Reconcile declared quality evidence and block explicit failures."""

    name = "DataQualitySpecialist"
    domain_role = "Data Quality & Integrity Review Specialist"
    description = "Reviews completeness, duplicates, findings, and integrity-check outcomes."
    mission = "Determine whether existing quality evidence is safe enough for analysis."
    responsibilities = (
        "Summarize observed quality findings by severity",
        "Reconcile integrity checks with the declared validation status",
        "Block explicit failures and critical data-quality findings",
    )
    required_inputs = ("schema_profile", "integrity_checks", "validation_status")
    outputs = ("data_quality_review",)
    quality_gates = (
        "No failed integrity check is passed downstream",
        "Critical findings block analysis",
        "Warnings remain visible and are never silently treated as passes",
    )
    escalation_conditions = (
        "Validation evidence is missing",
        "High-severity findings require business review",
        "The declared status conflicts with check results",
    )

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        profile = _mapping(state, "schema_profile", self.name)
        _count(profile.get("row_count"), "schema_profile.row_count", self.name)
        checks = _records(state, "integrity_checks", self.name, required=True)
        findings = _records(state, "quality_findings", self.name)
        validation = str(state.get("validation_status") or "").strip().lower()
        if validation not in {"pass", "warning", "fail"}:
            raise DataSpecialistContractError(
                "DataQualitySpecialist requires validation_status to be Pass, Warning, or Fail."
            )

        failed = [str(item.get("check_id") or item.get("check") or "unnamed") for item in checks if str(item.get("status") or "").lower() == "fail"]
        severities = Counter(str(item.get("severity") or "unspecified").lower() for item in findings)
        critical = [
            str(item.get("column") or item.get("issue") or "unnamed finding")
            for item in findings
            if str(item.get("severity") or "").lower() == "critical"
        ]
        if validation == "fail" or failed or critical:
            reasons = []
            if validation == "fail":
                reasons.append("declared validation status is Fail")
            if failed:
                reasons.append("failed integrity checks: " + ", ".join(failed))
            if critical:
                reasons.append("critical findings: " + ", ".join(critical))
            raise DataSpecialistContractError(
                "DataQualitySpecialist blocked analysis because " + "; ".join(reasons) + "."
            )
        if validation == "pass" and any(
            str(item.get("status") or "").lower() == "warning" for item in checks
        ):
            raise DataSpecialistContractError(
                "DataQualitySpecialist found validation_status Pass despite warning integrity checks."
            )

        high_findings = severities.get("high", 0)
        escalations = []
        if high_findings:
            escalations.append(f"Review {high_findings} high-severity quality finding(s).")
        if not checks:
            escalations.append("Run and record deterministic integrity checks before analysis.")
        if validation == "warning":
            escalations.append("Resolve or explicitly accept the declared validation warnings.")
        review = _review(
            type(self),
            status="review_required" if escalations else "ready",
            checks=[
                {"check": "declared_validation", "status": validation},
                {"check": "failed_integrity_checks", "status": "pass", "failed": []},
                {
                    "check": "critical_findings",
                    "status": "pass",
                    "critical_count": 0,
                },
            ],
            escalation_reasons=escalations,
            integrity_check_count=len(checks),
            quality_finding_count=len(findings),
            severity_counts=dict(sorted(severities.items())),
            decision="Conditionally usable" if escalations else "Usable for planned analysis",
        )
        return {"data_quality_review": review}


class CleaningSpecialist(_DataReviewSpecialist):
    """Audit conservative cleaning evidence without transforming any records."""

    name = "CleaningSpecialist"
    domain_role = "Cleaning Reconciliation & Reproducibility Specialist"
    description = "Checks row reconciliation, transformation policy, and cleaning audit coverage."
    mission = "Verify that the cleaned output is reproducible and does not silently change business meaning."
    responsibilities = (
        "Reconcile input, removed, and retained row counts",
        "Reject unapproved meaning-changing imputation",
        "Confirm that every cleaning run retains an audit record",
    )
    required_inputs = ("cleaned_path", "final_summary", "cleaning_checklist", "cleaning_log")
    outputs = ("cleaning_review",)
    quality_gates = (
        "Row counts reconcile exactly",
        "Meaning-changing imputation is not silently performed",
        "The cleaned artifact and audit log are declared",
    )
    escalation_conditions = (
        "Rows increase without an approved join audit",
        "Cleaning actions lack a reproducible log",
        "A transformation changes business meaning",
    )

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        summary = _mapping(state, "final_summary", self.name)
        checklist = _mapping(state, "cleaning_checklist", self.name)
        cleaning_log = _records(state, "cleaning_log", self.name, required=True)
        cleaned_path = str(state.get("cleaned_path") or "").strip()
        if not cleaned_path:
            raise DataSpecialistContractError("CleaningSpecialist requires a declared 'cleaned_path'.")

        before = _count(summary.get("rows_before"), "final_summary.rows_before", self.name)
        after = _count(summary.get("rows_after"), "final_summary.rows_after", self.name)
        removed = _count(summary.get("rows_removed"), "final_summary.rows_removed", self.name)
        if before - removed != after:
            raise DataSpecialistContractError(
                "CleaningSpecialist found unreconciled row counts: "
                f"{before} before - {removed} removed != {after} after."
            )
        if after > before:
            raise DataSpecialistContractError(
                "CleaningSpecialist found unexpected row expansion in a cleaning-only stage."
            )
        if checklist.get("meaning_changing_imputation_performed") is True:
            raise DataSpecialistContractError(
                "CleaningSpecialist blocked an output with meaning-changing imputation."
            )

        transformations = checklist.get("transformations", [])
        if not isinstance(transformations, Sequence) or isinstance(transformations, (str, bytes)):
            raise DataSpecialistContractError(
                "CleaningSpecialist requires cleaning_checklist.transformations to be a list."
            )
        escalations = []
        if not cleaning_log:
            escalations.append("Add an explicit no-change entry or transformation record to the cleaning log.")
        if checklist.get("meaning_changing_imputation_performed") is None:
            escalations.append("Explicitly declare whether meaning-changing imputation was performed.")
        review = _review(
            type(self),
            status="review_required" if escalations else "ready",
            checks=[
                {"check": "row_reconciliation", "status": "pass", "rows_before": before, "rows_removed": removed, "rows_after": after},
                {"check": "meaning_changing_imputation", "status": "pass" if checklist.get("meaning_changing_imputation_performed") is False else "warning"},
                {"check": "audit_log_present", "status": "pass" if cleaning_log else "warning", "entries": len(cleaning_log)},
            ],
            escalation_reasons=escalations,
            cleaned_artifact_declared=True,
            transformation_count=len(transformations),
            audit_entry_count=len(cleaning_log),
            policy="Review only; no additional transformation performed.",
        )
        return {"cleaning_review": review}


class PrivacyBiasSpecialist(_DataReviewSpecialist):
    """Flag privacy and representativeness risks without claiming legal clearance."""

    name = "PrivacyBiasSpecialist"
    domain_role = "Privacy, Permission & Bias Risk Specialist"
    description = "Reviews declared permissions and flags potential sensitive or subgroup fields for human review."
    mission = "Prevent unsafe distribution and unsupported fairness claims while preserving human authority."
    responsibilities = (
        "Review explicit licence and privacy declarations",
        "Flag potential identifier and sensitive-attribute columns",
        "Keep representativeness and fairness unverified until supported by evidence",
    )
    required_inputs = ("roccc_answers", "schema_profile")
    outputs = ("privacy_bias_review",)
    quality_gates = (
        "Permission is never inferred from data availability",
        "Potential sensitive fields remain visible",
        "No fairness or representativeness claim is invented",
    )
    escalation_conditions = (
        "Licence or privacy restrictions are unresolved",
        "Potential direct identifiers or sensitive attributes are present",
        "External distribution is requested without explicit permission",
    )

    _SENSITIVE_TOKENS: ClassVar[set[str]] = {
        "address", "birth", "dob", "email", "ethnicity", "gender", "health",
        "income", "name", "passport", "phone", "race", "religion", "salary",
        "ssn", "zip",
    }

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        roccc = state.get("roccc_answers")
        if roccc is None:
            roccc = {}
        if not isinstance(roccc, Mapping):
            raise DataSpecialistContractError(
                "PrivacyBiasSpecialist requires 'roccc_answers' to be a structured mapping."
            )
        profile = _mapping(state, "schema_profile", self.name)
        columns = profile.get("columns")
        if not isinstance(columns, Mapping):
            raise DataSpecialistContractError(
                "PrivacyBiasSpecialist requires 'schema_profile.columns' to be a mapping."
            )

        potential_sensitive: list[dict[str, Any]] = []
        for name in columns:
            tokens = {token for token in re.split(r"[^a-z0-9]+", str(name).lower()) if token}
            matched = sorted(tokens & self._SENSITIVE_TOKENS)
            if matched:
                potential_sensitive.append({"column": str(name), "matched_risk_tokens": matched})

        permission = str(roccc.get("source_license") or "").strip()
        privacy = str(roccc.get("privacy_restrictions") or "").strip()
        combined = f"{permission} {privacy}".lower()
        explicit_restriction = any(
            phrase in combined
            for phrase in ("not approved", "no permission", "prohibited", "do not distribute")
        )
        escalations = []
        if not permission:
            escalations.append("Obtain an explicit licence or permission statement.")
        if not privacy:
            escalations.append("Confirm privacy restrictions and intended distribution scope.")
        if potential_sensitive:
            escalations.append("Review potential sensitive fields before analysis or distribution.")
        if explicit_restriction:
            escalations.append("The supplied declaration contains an explicit use or distribution restriction.")

        status = "restricted" if explicit_restriction else "review_required" if escalations else "ready"
        review = _review(
            type(self),
            status=status,
            checks=[
                {"check": "permission_declared", "status": "pass" if permission else "warning"},
                {"check": "privacy_scope_declared", "status": "pass" if privacy else "warning"},
                {"check": "potential_sensitive_fields", "status": "warning" if potential_sensitive else "pass", "count": len(potential_sensitive)},
            ],
            escalation_reasons=escalations,
            potential_sensitive_columns=potential_sensitive,
            permission_statement=permission or "Not supplied",
            privacy_statement=privacy or "Not supplied",
            representativeness_status="Not assessed from the supplied workflow evidence.",
            fairness_status="No fairness conclusion made.",
            legal_clearance="Not provided; this review is not legal advice.",
        )
        return {"privacy_bias_review": review}


__all__ = [
    "CleaningSpecialist",
    "DataIntakeSpecialist",
    "DataQualitySpecialist",
    "DataSpecialistContractError",
    "PrivacyBiasSpecialist",
    "SchemaSpecialist",
]
