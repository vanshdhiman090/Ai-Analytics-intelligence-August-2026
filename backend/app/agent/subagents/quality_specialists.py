"""Independent, deterministic reviewers for analytical release decisions.

The reviewers in this module are deliberately read-only.  They inspect a run
state and append audit decisions; they never repair, rewrite, or otherwise
mutate findings, evidence, or publication gates.  Remediation belongs to the
specialist that produced the rejected work.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal, Sequence

from app.agent.subagents.base import BaseSubAgent


ReviewStatus = Literal["pass", "fail", "not_applicable"]


@dataclass(frozen=True)
class ReviewIssue:
    """A deterministic, machine-readable reason for a review decision."""

    code: str
    message: str
    references: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReviewDecision:
    """Immutable output from one independent quality specialist."""

    reviewer: str
    stage: str
    status: ReviewStatus
    blocking: bool
    summary: str
    checks: tuple[str, ...]
    issues: tuple[ReviewIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalise_stage(stage: object) -> str:
    value = str(stage or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "analysis": "analyze",
        "delivery": "share",
        "recommend": "act",
        "recommendations": "act",
        "deliverable": "deliverables",
        "publish": "publication",
    }
    return aliases.get(value, value)


def _record_id(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return "unidentified"


class DeterministicQualityReviewer(BaseSubAgent):
    """Base contract for reviewers that may only add audit information."""

    applicable_stages: frozenset[str] = frozenset()
    checks: tuple[str, ...] = ()

    def execute(self, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        stage = _normalise_stage(kwargs.get("stage") or state.get("current_stage") or state.get("stage"))
        if stage not in self.applicable_stages:
            decision = ReviewDecision(
                reviewer=self.name,
                stage=stage,
                status="not_applicable",
                blocking=False,
                summary=f"{self.name} does not review the {stage!r} stage.",
                checks=self.checks,
            )
        else:
            decision = self.review(state, stage)

        # Build a fresh list.  In particular, do not append to the list held by
        # state because workflow state can be shared by multiple reviewers.
        existing = list(state.get("quality_reviews") or [])
        return {"quality_reviews": [*existing, decision.to_dict()]}

    @abstractmethod
    def review(self, state: dict[str, Any], stage: str) -> ReviewDecision:
        """Inspect state without modifying it and return one decision."""

    def _decision(self, stage: str, issues: Sequence[ReviewIssue], success: str) -> ReviewDecision:
        frozen_issues = tuple(issues)
        return ReviewDecision(
            reviewer=self.name,
            stage=stage,
            status="fail" if frozen_issues else "pass",
            blocking=bool(frozen_issues),
            summary=frozen_issues[0].message if frozen_issues else success,
            checks=self.checks,
            issues=frozen_issues,
        )


class CalculationReviewer(DeterministicQualityReviewer):
    """Review calculation readiness and material deterministic check failures."""

    name = "CalculationReviewer"
    domain_role = "Independent Calculation Integrity Specialist"
    description = "Checks validation, integrity tests, and evidence calculation status without recalculating or editing results."
    applicable_stages = frozenset({"analyze", "share", "act", "deliverables", "package", "publication"})
    checks = ("dataset_validation", "integrity_checks", "evidence_quality_status", "governed_comparison_context")

    def review(self, state: dict[str, Any], stage: str) -> ReviewDecision:
        issues: list[ReviewIssue] = []
        validation_status = str(state.get("validation_status") or "unknown").strip().lower()
        if validation_status == "fail":
            issues.append(ReviewIssue("DATASET_VALIDATION_FAILED", "Dataset validation failed; calculations are not releasable."))

        failed_checks: list[str] = []
        for item in state.get("integrity_checks") or []:
            if str(item.get("status") or "").strip().lower() != "fail":
                continue
            severity = str(item.get("severity") or "critical").strip().lower()
            if severity not in {"advisory", "info", "warning"}:
                failed_checks.append(_record_id(item, "check_id", "check"))
        if failed_checks:
            issues.append(
                ReviewIssue(
                    "MATERIAL_INTEGRITY_CHECK_FAILED",
                    "One or more material process integrity checks failed.",
                    tuple(sorted(failed_checks)),
                )
            )

        insufficient_evidence = sorted(
            _record_id(item, "evidence_id")
            for item in state.get("evidence") or []
            if str(item.get("quality_status") or "ready").strip().lower() in {"fail", "failed", "insufficient"}
        )
        if insufficient_evidence:
            issues.append(
                ReviewIssue(
                    "EVIDENCE_CALCULATION_INSUFFICIENT",
                    "Evidence marked insufficient or failed cannot support release.",
                    tuple(insufficient_evidence),
                )
            )

        context = state.get("comparison_context") or {}
        if context:
            expected = (str(context.get("baseline_period")), str(context.get("comparison_period")))
            mismatches: list[str] = []
            for item in state.get("evidence") or []:
                if item.get("kind") not in {"trend", "period_comparison", "segment_change"}:
                    continue
                diagnostics = item.get("diagnostics") or {}
                actual = (str(diagnostics.get("baseline_period")), str(diagnostics.get("comparison_period")))
                if actual != expected:
                    mismatches.append(_record_id(item, "evidence_id"))
            report = state.get("root_cause_report") or {}
            incident = report.get("incident") or {}
            if incident and (str(incident.get("baseline_period")), str(incident.get("comparison_period"))) != expected:
                mismatches.append("root_cause_report")
            if mismatches:
                issues.append(
                    ReviewIssue(
                        "COMPARISON_CONTEXT_MISMATCH",
                        "Evidence or RCA does not match the governed comparison period pair.",
                        tuple(sorted(mismatches)),
                    )
                )

        return self._decision(stage, issues, "No material calculation-integrity failure was detected.")


class EvidenceCritic(DeterministicQualityReviewer):
    """Review evidence availability and finding-to-evidence traceability."""

    name = "EvidenceCritic"
    domain_role = "Independent Evidence and Citation Specialist"
    description = "Blocks empty analytical evidence, duplicate identifiers, and unresolved finding citations."
    applicable_stages = frozenset({"analyze", "share", "act", "deliverables", "package", "publication"})
    checks = ("non_empty_evidence", "unique_evidence_ids", "finding_citations")

    def review(self, state: dict[str, Any], stage: str) -> ReviewDecision:
        evidence = list(state.get("evidence") or [])
        findings = list(state.get("findings") or [])
        issues: list[ReviewIssue] = []

        if not evidence:
            issues.append(ReviewIssue("EMPTY_EVIDENCE", "No computed evidence is available for independent review."))

        evidence_ids = [_record_id(item, "evidence_id") for item in evidence]
        duplicate_ids = sorted({item_id for item_id in evidence_ids if evidence_ids.count(item_id) > 1})
        if duplicate_ids:
            issues.append(
                ReviewIssue(
                    "DUPLICATE_EVIDENCE_ID",
                    "Evidence identifiers must be unique for reliable citation resolution.",
                    tuple(duplicate_ids),
                )
            )

        known_ids = set(evidence_ids)
        missing_citations: list[str] = []
        unresolved: list[str] = []
        for finding in findings:
            finding_id = _record_id(finding, "finding_id")
            citations = [str(item).strip() for item in finding.get("evidence_ids") or [] if str(item).strip()]
            if not citations:
                missing_citations.append(finding_id)
            unresolved.extend(f"{finding_id}->{citation}" for citation in citations if citation not in known_ids)

        if missing_citations:
            issues.append(
                ReviewIssue(
                    "FINDING_WITHOUT_CITATION",
                    "Every finding must cite at least one evidence record.",
                    tuple(sorted(missing_citations)),
                )
            )
        if unresolved:
            issues.append(
                ReviewIssue(
                    "UNRESOLVED_EVIDENCE_CITATION",
                    "One or more finding citations do not resolve to supplied evidence.",
                    tuple(sorted(unresolved)),
                )
            )

        return self._decision(stage, issues, "Evidence is present and every finding citation resolves.")


_CAUSAL_LANGUAGE = re.compile(r"\b(causes?|caused|causing|leads? to|resulted in)\b", re.IGNORECASE)
_AMBIGUOUS_CONTRIBUTION_LANGUAGE = re.compile(r"\bdrives?\b", re.IGNORECASE)
_CONTRIBUTION_CONTEXT = re.compile(r"\b(change|movement|contribution|decomposition|period)\b", re.IGNORECASE)


class CausalLanguageReviewer(DeterministicQualityReviewer):
    """Block causal conclusions that are unsupported by the evidence contract."""

    name = "CausalLanguageReviewer"
    domain_role = "Independent Causal-Claims Specialist"
    description = "Separates descriptive arithmetic contributions from unsupported causal conclusions."
    applicable_stages = frozenset({"analyze", "share", "act", "deliverables", "package", "publication"})
    checks = ("causal_wording", "segment_change_exception")

    def review(self, state: dict[str, Any], stage: str) -> ReviewDecision:
        evidence_by_id = {
            _record_id(item, "evidence_id"): item
            for item in state.get("evidence") or []
        }
        unsupported: list[str] = []
        for finding in state.get("findings") or []:
            finding_id = _record_id(finding, "finding_id")
            claim = f"{finding.get('statement', '')} {finding.get('implication', '')}".strip()
            strong_causal_wording = _CAUSAL_LANGUAGE.search(claim)
            ambiguous_drive = _AMBIGUOUS_CONTRIBUTION_LANGUAGE.search(claim)
            cited_evidence = [
                evidence_by_id.get(str(reference), {})
                for reference in finding.get("evidence_ids") or []
            ]
            reconciled_contribution = bool(
                ambiguous_drive
                and _CONTRIBUTION_CONTEXT.search(claim)
                and cited_evidence
                and all(item.get("kind") == "segment_change" for item in cited_evidence)
            )
            if strong_causal_wording or (ambiguous_drive and not reconciled_contribution):
                unsupported.append(finding_id)

        issues: list[ReviewIssue] = []
        if unsupported:
            issues.append(
                ReviewIssue(
                    "UNSUPPORTED_CAUSAL_WORDING",
                    "Potential causal wording is not supported by the descriptive evidence contract.",
                    tuple(sorted(unsupported)),
                )
            )
        return self._decision(stage, issues, "No unsupported causal wording was detected.")


class PublicationReviewer(DeterministicQualityReviewer):
    """Issue the final independent release decision from recorded gate results."""

    name = "PublicationReviewer"
    domain_role = "Independent Publication Release Specialist"
    description = "Blocks release when critical gates or earlier independent reviews remain failed."
    applicable_stages = frozenset({"package", "publication"})
    checks = ("quality_gate_presence", "material_gate_failures", "prior_independent_reviews")

    def review(self, state: dict[str, Any], stage: str) -> ReviewDecision:
        issues: list[ReviewIssue] = []
        gates = list(state.get("quality_gates") or [])
        if not gates:
            issues.append(ReviewIssue("QUALITY_GATES_MISSING", "Publication quality gates have not been recorded."))
        else:
            failed_gates = sorted(
                _record_id(item, "gate_id", "name")
                for item in gates
                if str(item.get("status") or "").strip().lower() in {"fail", "failed", "block", "blocked"}
                and str(item.get("severity") or "critical").strip().lower() not in {"advisory", "info", "warning"}
            )
            if failed_gates:
                issues.append(
                    ReviewIssue(
                        "MATERIAL_PUBLICATION_GATE_FAILED",
                        "One or more material publication gates failed.",
                        tuple(failed_gates),
                    )
                )

        earlier_failures = sorted(
            str(item.get("reviewer") or "UnknownReviewer")
            for item in state.get("quality_reviews") or []
            if item.get("reviewer") != self.name
            and str(item.get("status") or "").strip().lower() == "fail"
            and bool(item.get("blocking", True))
        )
        if earlier_failures:
            issues.append(
                ReviewIssue(
                    "PRIOR_QUALITY_REVIEW_FAILED",
                    "An earlier independent quality review remains unresolved.",
                    tuple(earlier_failures),
                )
            )

        return self._decision(stage, issues, "All recorded material gates and independent reviews permit publication.")


QUALITY_REVIEWERS: tuple[DeterministicQualityReviewer, ...] = (
    CalculationReviewer(),
    EvidenceCritic(),
    CausalLanguageReviewer(),
    PublicationReviewer(),
)


def run_quality_reviewers(
    state: dict[str, Any],
    stage: str | None = None,
    reviewers: Iterable[DeterministicQualityReviewer] | None = None,
) -> dict[str, Any]:
    """Run reviewers in order and return only additive workflow-state updates.

    All reviewers run so the audit trail explicitly records when a specialist
    is not applicable.  A failed blocking decision never prevents the other
    independent reviewers from reporting their own result.
    """

    resolved_stage = _normalise_stage(stage or state.get("current_stage") or state.get("stage"))
    audit = list(state.get("quality_reviews") or [])
    for reviewer in reviewers or QUALITY_REVIEWERS:
        review_state = {**state, "quality_reviews": audit}
        audit = reviewer.execute(review_state, stage=resolved_stage)["quality_reviews"]

    current_decisions = [item for item in audit if item.get("stage") == resolved_stage]
    blocking_failures = sorted(
        item["reviewer"]
        for item in current_decisions
        if item.get("status") == "fail" and item.get("blocking")
    )
    summary = {
        "stage": resolved_stage,
        "status": "fail" if blocking_failures else "pass",
        "blocking": bool(blocking_failures),
        "failed_reviewers": blocking_failures,
        "reviewed_by": [item["reviewer"] for item in current_decisions],
    }
    return {"quality_reviews": audit, "quality_review_summary": summary}
