"""Neutral post-phase packaging and publication of validated deliverables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypedDict

from app.core.config import settings
from app.core.database import SessionLocal
from app.domain.contracts import ActionPackage
from app.models.schema import AgentAction, Artifact, Session as SessionModel
from app.services.presentation_deck import create_stakeholder_pptx
from app.services.project_files import create_project_bundle
from app.services.reporting import write_deliverables


class PackageState(TypedDict, total=False):
    session_id: str
    business_question: str
    original_filename: str
    source_sha256: str
    cleaned_path: str
    analysis_brief: dict
    analysis_summary: str
    metric_semantics: dict
    root_cause_report: dict
    comparison_context: dict
    schema_profile: dict
    source_register: list
    roccc_answers: dict
    cleaning_checklist: dict
    cleaning_log: list
    integrity_checks: list
    validation_status: str
    quality_findings: list
    final_summary: dict
    analysis_plan: dict
    evidence: list
    findings: list
    chart_paths: dict
    action_package: dict
    recommendations: list
    limitations: list
    monitoring_metrics: list
    additional_deliverables: list
    quality_gates: list
    requested_outputs: list[str]
    report_style: str


# "Drives" is ambiguous: for a segment-change decomposition it can mean a
# reconciled arithmetic contribution to observed movement. That narrow case is
# handled below; the other terms are unambiguously causal in this product.
CAUSAL_LANGUAGE = re.compile(r"\b(causes?|caused|causing|leads? to|resulted in)\b", re.IGNORECASE)
AMBIGUOUS_CONTRIBUTION_LANGUAGE = re.compile(r"\bdrives?\b", re.IGNORECASE)
CONTRIBUTION_CONTEXT = re.compile(r"\b(change|movement|contribution|decomposition|period)\b", re.IGNORECASE)


def validate_package(state: PackageState, package: ActionPackage) -> list[dict[str, Any]]:
    """Run deterministic publication gates before any final document is created."""
    evidence_ids = {str(item.get("evidence_id")) for item in state.get("evidence", [])}
    finding_ids = {str(item.get("finding_id")) for item in state.get("findings", [])}
    gates: list[dict[str, Any]] = []

    def gate(gate_id: str, name: str, passed: bool, detail: str, severity: str = "critical") -> None:
        gates.append({"gate_id": gate_id, "name": name, "status": "Pass" if passed else "Fail", "severity": severity, "detail": detail})

    plan_operations = (state.get("analysis_plan") or {}).get("operations") or []
    analysis_complete = bool(plan_operations) and bool(state.get("evidence")) and bool(state.get("findings"))
    gate(
        "QG0",
        "Minimum publishable analysis",
        analysis_complete,
        "The analysis contains an executable plan, validated evidence, and evidence-linked findings."
        if analysis_complete
        else "Publication blocked: an executable plan, validated evidence, and at least one finding are required.",
    )

    unknown_evidence = sorted({ref for item in state.get("findings", []) for ref in item.get("evidence_ids", []) if ref not in evidence_ids})
    gate("QG1", "Finding-to-evidence traceability", not unknown_evidence, "All finding citations resolve." if not unknown_evidence else f"Unknown evidence IDs: {unknown_evidence}")

    unknown_findings = sorted({ref for item in package.recommendations for ref in item.finding_ids if ref not in finding_ids})
    gate("QG2", "Recommendation-to-finding traceability", not unknown_findings, "All recommendation citations resolve." if not unknown_findings else f"Unknown finding IDs: {unknown_findings}")

    missing_population = [item.get("evidence_id") for item in state.get("evidence", []) if not str(item.get("population") or "").strip()]
    gate("QG3", "Denominator and population disclosure", not missing_population, "Every evidence record states its population." if not missing_population else f"Missing population: {missing_population}")

    evidence_by_id = {str(item.get("evidence_id")): item for item in state.get("evidence", [])}
    causal_claims: list[str] = []
    for item in state.get("findings", []):
        claim = f"{item.get('statement', '')} {item.get('implication', '')}"
        strong_causal_wording = CAUSAL_LANGUAGE.search(claim)
        ambiguous_drive = AMBIGUOUS_CONTRIBUTION_LANGUAGE.search(claim)
        cited_evidence = [evidence_by_id.get(str(ref), {}) for ref in item.get("evidence_ids", [])]
        is_reconciled_contribution = (
            ambiguous_drive
            and CONTRIBUTION_CONTEXT.search(claim)
            and cited_evidence
            and all(item.get("kind") == "segment_change" for item in cited_evidence)
        )
        if strong_causal_wording or (ambiguous_drive and not is_reconciled_contribution):
            causal_claims.append(f"{item.get('finding_id')}: {claim[:240]}")
    gate("QG4", "Unsupported causal-language check", not causal_claims, "No unsupported causal wording detected." if not causal_claims else f"Potential causal wording in: {causal_claims}")

    source_answer = str((state.get("roccc_answers") or {}).get("source_license") or "").strip()
    gate("QG5", "Source and licence disclosure", bool(source_answer), "Source/licence response recorded." if source_answer else "Source/licence response is missing.")

    failed_integrity = [item.get("check_id") or item.get("check") for item in state.get("integrity_checks", []) if str(item.get("status", "")).lower() == "fail"]
    gate("QG6", "Process integrity checks", not failed_integrity, "No failed integrity checks." if not failed_integrity else f"Failed checks: {failed_integrity}")

    chart_paths = state.get("chart_paths") or {}
    orphan_charts = sorted(set(chart_paths) - evidence_ids)
    missing_chart_files = sorted(evidence_id for evidence_id, path in chart_paths.items() if not Path(path).is_file())
    chart_traceability_ok = not orphan_charts and not missing_chart_files
    chart_detail = "Every chart resolves to evidence and an existing file."
    if orphan_charts or missing_chart_files:
        chart_detail = f"Orphan chart IDs: {orphan_charts}; missing chart files: {missing_chart_files}"
    gate("QG7", "Chart-to-evidence provenance", chart_traceability_ok, chart_detail)

    chartable_ids = {
        str(item.get("evidence_id"))
        for item in state.get("evidence", [])
        if item.get("kind") in {"grouped_aggregate", "trend", "period_comparison", "distribution", "outlier_analysis", "correlation", "kpi_ratio", "statistical_comparison", "segment_change"}
    }
    missing_visuals = sorted(chartable_ids - set(chart_paths))
    gate(
        "QG8",
        "Visual evidence coverage",
        not missing_visuals,
        "Every chartable evidence record has a visual." if not missing_visuals else f"No suitable visual was produced for: {missing_visuals}",
        severity="advisory",
    )

    incomplete_findings = [
        item.get("finding_id")
        for item in state.get("findings", [])
        if not str(item.get("statement") or "").strip()
        or not str(item.get("implication") or "").strip()
        or str(item.get("confidence") or "").lower() not in {"high", "medium", "low"}
    ]
    narrative_ready = bool(str(state.get("analysis_summary") or "").strip()) and not incomplete_findings
    gate(
        "QG9",
        "Executive narrative readiness",
        narrative_ready,
        "The summary and every finding include a claim, implication, and confidence rating."
        if narrative_ready
        else f"Summary missing: {not bool(str(state.get('analysis_summary') or '').strip())}; incomplete findings: {incomplete_findings}",
    )

    placeholder_values = {"", "unknown", "unspecified", "tbd", "n/a", "none"}
    incomplete_actions = [
        item.recommendation_id
        for item in package.recommendations
        if item.owner_role.strip().lower() in placeholder_values or item.timeframe.strip().lower() in placeholder_values
    ]
    gate(
        "QG10",
        "Action ownership and timing",
        not incomplete_actions,
        "Every recommendation names an owner role and timeframe." if not incomplete_actions else f"Incomplete actions: {incomplete_actions}",
    )

    validation_status = str(state.get("validation_status") or "Unknown")
    gate(
        "QG11",
        "Dataset validation status",
        validation_status.lower() != "fail",
        f"Dataset validation status: {validation_status}.",
    )

    gate(
        "QG12",
        "Limitations disclosure",
        bool(package.limitations),
        "Limitations are visible in the deliverables." if package.limitations else "No limitation was disclosed.",
    )

    context = state.get("comparison_context") or {}
    if context:
        expected = (str(context.get("baseline_period")), str(context.get("comparison_period")))
        time_evidence = [
            item for item in state.get("evidence", [])
            if item.get("kind") in {"trend", "period_comparison", "segment_change"}
        ]
        mismatch = [
            str(item.get("evidence_id")) for item in time_evidence
            if (str((item.get("diagnostics") or {}).get("baseline_period")), str((item.get("diagnostics") or {}).get("comparison_period"))) != expected
        ]
        incident = (state.get("root_cause_report") or {}).get("incident") or {}
        if incident and (str(incident.get("baseline_period")), str(incident.get("comparison_period"))) != expected:
            mismatch.append("root_cause_report")
        gate(
            "QG13",
            "Governed comparison-context consistency",
            not mismatch,
            f"All time evidence and RCA use {expected[0]} to {expected[1]}." if not mismatch else f"Comparison-context mismatch: {sorted(mismatch)}",
        )

        segment_evidence = any(item.get("kind") == "segment_change" for item in state.get("evidence", []))
        narrative = " ".join(
            [str(state.get("analysis_summary") or "")]
            + [f"{item.get('statement', '')} {item.get('implication', '')}" for item in state.get("findings", [])]
        ).lower()
        false_absence = bool(segment_evidence and re.search(r"(?:segment(?:[- ]decomposition| evidence)|decomposition).{0,60}(?:unavailable|not available|absent)", narrative))
        gate(
            "QG14",
            "Segment-evidence narrative consistency",
            not false_absence,
            "The narrative does not deny available segment-decomposition evidence." if not false_absence else "The narrative says segment decomposition is unavailable although validated segment evidence exists.",
        )

    failed = [item for item in gates if item["status"] == "Fail" and item["severity"] == "critical"]
    if failed:
        raise ValueError("Publication quality gate failed: " + "; ".join(item["detail"] for item in failed))
    return gates


def package_node(state: PackageState) -> PackageState:
    package = ActionPackage.model_validate(state["action_package"])
    quality_gates = validate_package(state, package)
    artifact_dir = settings.DATA_DIR / "runs" / state["session_id"] / "artifacts"
    requested = set(state.get("requested_outputs") or [])
    # The analysis result always persists. Files are produced only after the
    # user has selected them at the final deliverables checkpoint.
    wants_report = bool(requested & {"executive_report", "professional_case_study", "technical_report"})
    documents = write_deliverables({**state, "quality_gates": quality_gates, "report_style": state.get("report_style", "executive")}, package, artifact_dir) if wants_report else []
    presentation_path = create_stakeholder_pptx({**state, "quality_gates": quality_gates}, package, artifact_dir) if "presentation" in requested else None
    project_bundle = create_project_bundle({**state, "quality_gates": quality_gates}, artifact_dir) if "project_zip" in requested else None

    result_summary = {
        "question": state["business_question"],
        "summary": state["analysis_summary"],
        "findings": state.get("findings", []),
        "recommendations": [item.model_dump(mode="json") for item in package.recommendations],
        "limitations": package.limitations,
        "monitoring_metrics": package.monitoring_metrics,
        "unanswered_questions": state.get("additional_deliverables", []),
        "analysis_brief": state.get("analysis_brief", {}),
        "schema_profile": state.get("schema_profile", {}),
        "source_register": state.get("source_register", []),
        "roccc_answers": state.get("roccc_answers", {}),
        "cleaning_checklist": state.get("cleaning_checklist", {}),
        "cleaning_log": state.get("cleaning_log", []),
        "integrity_checks": state.get("integrity_checks", []),
        "validation_status": state.get("validation_status", "Unknown"),
        "quality_findings": state.get("quality_findings", []),
        "final_summary": state.get("final_summary", {}),
        "analysis_plan": state.get("analysis_plan", {}),
        "evidence": state.get("evidence", []),
        "metric_semantics": state.get("metric_semantics"),
        "root_cause_report": state.get("root_cause_report"),
        "comparison_context": state.get("comparison_context"),
        "quality_gates": quality_gates,
    }

    db = SessionLocal()
    try:
        session = db.query(SessionModel).filter(SessionModel.id == state["session_id"]).first()
        if session is None:
            raise RuntimeError("Session no longer exists")
        session.result_summary = result_summary
        for document in documents:
            db.add(Artifact(session_id=state["session_id"], type=document.artifact_type, file_path=str(artifact_dir / document.filename), metadata_={"format": "html", "title": document.title, "description": document.description, "document_type": document.document_type, "finding_count": len(state.get("findings", [])), "quality_gate_status": "Pass"}))
        if presentation_path:
            db.add(Artifact(session_id=state["session_id"], type="presentation", file_path=str(presentation_path), metadata_={"format": "pptx", "title": "Stakeholder Presentation", "description": "Editable native PowerPoint with stakeholder-ready narrative, charts, recommendations, and source notes", "document_type": "stakeholder_presentation", "quality_gate_status": "Pass"}))
        if project_bundle:
            db.add(Artifact(session_id=state["session_id"], type="project_files", file_path=str(project_bundle), metadata_={"format": "zip", "title": "Project Files", "description": "Reproducible notebook, full analysis code, cleaned data, charts, validated outputs, and raw-data references", "document_type": "project_files", "quality_gate_status": "Pass"}))
        output_label = ", ".join(sorted(requested)) or "no files (analysis result only)"
        db.add(AgentAction(session_id=state["session_id"], stage="package", action_type="validated_case_study_package", input_summary=f"{len(state.get('findings', []))} findings and {len(package.recommendations)} recommendations", output_summary=f"Passed {len(quality_gates)} publication gates; user selected: {output_label}"))
        db.commit()
    finally:
        db.close()
    return {"quality_gates": quality_gates}
