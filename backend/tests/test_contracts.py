import pytest
from pydantic import ValidationError

from app.domain.contracts import (
    AnalysisBrief,
    DecisionPackage,
    EvidenceRef,
    Finding,
    Recommendation,
    Stakeholder,
)


def brief():
    return AnalysisBrief(
        objective="Understand which segment is driving the observed change.",
        decision="Decide which segment should receive further investigation.",
        primary_question="Which segment contributed most to the change and why?",
        stakeholders=[
            Stakeholder(name="Unspecified", role="Decision owner", decision_interest="Prioritization")
        ],
        success_criteria=["Quantify segment contributions using the supplied dataset."],
        in_scope=["Observed rows and documented fields"],
    )


def test_decision_package_requires_end_to_end_traceability():
    package = DecisionPackage(
        brief=brief(),
        evidence=[
            EvidenceRef(
                evidence_id="E1",
                operation_id="OP1",
                metric="revenue contribution",
                value=42.0,
                unit="percent",
                population="All supplied rows",
                method="Grouped sum",
            )
        ],
        findings=[
            Finding(
                finding_id="F1",
                statement="Segment A contributed 42%.",
                implication="Segment A is the largest observed contributor.",
                evidence_ids=["E1"],
                confidence="high",
            )
        ],
        recommendations=[
            Recommendation(
                recommendation_id="R1",
                action="Investigate Segment A's underlying drivers.",
                rationale="It is the largest observed contributor.",
                finding_ids=["F1"],
                owner_role="Decision owner",
                timeframe="Next planning cycle",
                expected_impact="unknown",
                effort="unknown",
            )
        ],
        limitations=[],
    )
    assert package.recommendations[0].finding_ids == ["F1"]


def test_decision_package_rejects_unsupported_finding():
    with pytest.raises(ValidationError, match="unknown evidence"):
        DecisionPackage(
            brief=brief(),
            evidence=[],
            findings=[
                Finding(
                    finding_id="F1",
                    statement="Unsupported statement",
                    implication="Unsupported implication",
                    evidence_ids=["E99"],
                    confidence="low",
                )
            ],
            recommendations=[],
            limitations=[],
        )
