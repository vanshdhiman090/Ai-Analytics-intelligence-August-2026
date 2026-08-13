from copy import deepcopy

from app.agent.subagents.base import BaseSubAgent
from app.agent.subagents.quality_specialists import (
    CalculationReviewer,
    CausalLanguageReviewer,
    EvidenceCritic,
    PublicationReviewer,
    QUALITY_REVIEWERS,
    run_quality_reviewers,
)


def valid_analysis_state():
    return {
        "validation_status": "Pass",
        "integrity_checks": [{"check_id": "IC1", "status": "Pass"}],
        "evidence": [
            {
                "evidence_id": "E1",
                "operation_id": "OP1",
                "kind": "grouped_aggregate",
                "population": "9 retained rows",
                "quality_status": "ready",
            }
        ],
        "findings": [
            {
                "finding_id": "F1",
                "statement": "Segment A has the highest observed total.",
                "implication": "Review the observed segment difference.",
                "evidence_ids": ["E1"],
                "confidence": "high",
            }
        ],
    }


def decision(update):
    return update["quality_reviews"][-1]


def test_reviewers_are_base_subagents_with_distinct_professional_roles():
    assert len(QUALITY_REVIEWERS) == 4
    assert all(isinstance(reviewer, BaseSubAgent) for reviewer in QUALITY_REVIEWERS)
    assert {reviewer.name for reviewer in QUALITY_REVIEWERS} == {
        "CalculationReviewer",
        "EvidenceCritic",
        "CausalLanguageReviewer",
        "PublicationReviewer",
    }
    assert all(reviewer.domain_role.startswith("Independent") for reviewer in QUALITY_REVIEWERS)


def test_non_applicable_stage_is_explicit_and_non_blocking():
    state = {"current_stage": "ask", "evidence": [], "findings": []}
    result = run_quality_reviewers(state)

    assert [item["status"] for item in result["quality_reviews"]] == ["not_applicable"] * 4
    assert result["quality_review_summary"]["status"] == "pass"
    assert result["quality_review_summary"]["blocking"] is False


def test_pipeline_is_additive_and_does_not_modify_evidence_or_findings():
    state = valid_analysis_state()
    state["quality_reviews"] = [{"reviewer": "EarlierReviewer", "stage": "prepare", "status": "pass", "blocking": False}]
    original = deepcopy(state)

    result = run_quality_reviewers(state, stage="analyze")

    assert state == original
    assert result["quality_reviews"][0] == original["quality_reviews"][0]
    assert len(result["quality_reviews"]) == 5
    assert result["quality_review_summary"]["status"] == "pass"
    assert result["quality_review_summary"]["reviewed_by"] == [reviewer.name for reviewer in QUALITY_REVIEWERS]


def test_evidence_critic_blocks_empty_and_unresolved_evidence():
    empty = decision(EvidenceCritic().execute({"evidence": [], "findings": []}, stage="analyze"))
    unresolved = decision(
        EvidenceCritic().execute(
            {
                "evidence": [{"evidence_id": "E1"}],
                "findings": [{"finding_id": "F1", "evidence_ids": ["E99"]}],
            },
            stage="analyze",
        )
    )

    assert empty["status"] == "fail" and empty["blocking"] is True
    assert {item["code"] for item in empty["issues"]} == {"EMPTY_EVIDENCE"}
    assert unresolved["status"] == "fail"
    assert unresolved["issues"][0]["code"] == "UNRESOLVED_EVIDENCE_CITATION"
    assert unresolved["issues"][0]["references"] == ("F1->E99",)


def test_calculation_reviewer_blocks_material_failures_but_not_advisories():
    state = valid_analysis_state()
    state["integrity_checks"] = [
        {"check_id": "IC-critical", "status": "Fail", "severity": "critical"},
        {"check_id": "IC-advice", "status": "Fail", "severity": "advisory"},
    ]
    result = decision(CalculationReviewer().execute(state, stage="share"))

    assert result["status"] == "fail"
    assert result["issues"][0]["code"] == "MATERIAL_INTEGRITY_CHECK_FAILED"
    assert result["issues"][0]["references"] == ("IC-critical",)


def test_causal_language_reviewer_blocks_unsupported_claims():
    state = valid_analysis_state()
    state["findings"][0]["statement"] = "Segment A caused higher value."

    result = decision(CausalLanguageReviewer().execute(state, stage="analyze"))

    assert result["status"] == "fail"
    assert result["issues"][0]["code"] == "UNSUPPORTED_CAUSAL_WORDING"
    assert result["issues"][0]["references"] == ("F1",)


def test_reconciled_segment_change_wording_is_not_treated_as_causal():
    state = valid_analysis_state()
    state["evidence"][0]["kind"] = "segment_change"
    state["findings"][0]["statement"] = "Segment A drives the observed period change."

    result = decision(CausalLanguageReviewer().execute(state, stage="analyze"))

    assert result["status"] == "pass"


def test_publication_reviewer_blocks_missing_or_material_failed_gates():
    missing = decision(PublicationReviewer().execute({}, stage="package"))
    failed = decision(
        PublicationReviewer().execute(
            {
                "quality_gates": [
                    {"gate_id": "QG7", "status": "Fail", "severity": "critical"},
                    {"gate_id": "QG8", "status": "Fail", "severity": "advisory"},
                ]
            },
            stage="publication",
        )
    )

    assert missing["status"] == "fail"
    assert missing["issues"][0]["code"] == "QUALITY_GATES_MISSING"
    assert failed["status"] == "fail"
    assert failed["issues"][0]["references"] == ("QG7",)


def test_publication_reviewer_blocks_unresolved_prior_review_and_ignores_advisory_gate():
    state = {
        "quality_gates": [{"gate_id": "QG8", "status": "Fail", "severity": "advisory"}],
        "quality_reviews": [
            {"reviewer": "EvidenceCritic", "stage": "analyze", "status": "fail", "blocking": True},
            {"reviewer": "ChartAdvisor", "stage": "share", "status": "fail", "blocking": False},
        ],
    }
    result = decision(PublicationReviewer().execute(state, stage="package"))

    assert result["status"] == "fail"
    assert result["issues"][0]["code"] == "PRIOR_QUALITY_REVIEW_FAILED"
    assert result["issues"][0]["references"] == ("EvidenceCritic",)


def test_clean_publication_gate_record_passes():
    result = decision(
        PublicationReviewer().execute(
            {"quality_gates": [{"gate_id": "QG1", "status": "Pass", "severity": "critical"}]},
            stage="package",
        )
    )
    assert result["status"] == "pass"
    assert result["blocking"] is False

