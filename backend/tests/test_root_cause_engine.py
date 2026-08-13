import pytest
from pydantic import ValidationError

from app.domain.root_cause_contracts import (
    DataHealthCheck,
    DriverInput,
    FalsificationCheck,
    HypothesisInput,
    IncidentInput,
    RCAEvidence,
    RCAInvestigationRequest,
    RCASemanticDefinition,
)
from app.services.root_cause import build_root_cause_report, investigate_root_cause
import pandas as pd


def evidence(*, causal: bool = False):
    return (
        RCAEvidence(evidence_id="E1", source_id="orders", description="KPI period comparison"),
        RCAEvidence(evidence_id="E2", source_id="orders", description="Segment decomposition"),
        RCAEvidence(
            evidence_id="E3",
            source_id="experiment" if causal else "orders",
            description="Mechanism test",
            evidence_type="experimental" if causal else "operational",
        ),
        RCAEvidence(evidence_id="E4", source_id="monitoring", description="Independent validation"),
    )


def request(**overrides):
    values = {
        "incident": IncidentInput(
            metric="revenue", baseline_period="2026-01", comparison_period="2026-02",
            baseline_value=1000, comparison_value=900, evidence_ids=("E1",),
        ),
        "evidence": evidence(),
        "data_health_checks": (
            DataHealthCheck(
                check_id="DH1", name="Completeness", status="pass", detail="Complete periods",
                evidence_ids=("E1", "E4"),
            ),
        ),
        "drivers": (
            DriverInput(driver_id="D1", name="Enterprise", baseline_value=600, comparison_value=510, evidence_ids=("E2", "E4")),
            DriverInput(driver_id="D2", name="SMB", baseline_value=400, comparison_value=390, evidence_ids=("E2", "E4")),
        ),
        "drivers_form_partition": True,
    }
    values.update(overrides)
    return RCAInvestigationRequest(**values)


def test_driver_contribution_and_reconciliation_are_deterministic():
    report = investigate_root_cause(request())

    assert report.incident.absolute_change == -100
    assert report.incident.percent_change == -10
    assert report.drivers[0].driver_id == "D1"
    assert report.drivers[0].absolute_change == -90
    assert report.drivers[0].contribution_to_total_change_pct == 90
    assert report.reconciliation.explained_change == -100
    assert report.reconciliation.unexplained_change == 0
    assert report.reconciliation.residual_within_tolerance is True
    assert report.conclusion.determination == "mathematical_driver_identified"
    assert report.conclusion.causal_claim_allowed is False


def test_competing_hypotheses_receive_explicit_statuses_and_falsification():
    hypotheses = (
        HypothesisInput(
            hypothesis_id="H1", statement="Checkout failures reduced revenue",
            supporting_evidence_ids=("E2",), mechanism_evidence_ids=("E3",),
            falsification_checks=(
                FalsificationCheck(check_id="FC1", description="Check unaffected traffic", outcome="survived", evidence_ids=("E4",)),
            ),
        ),
        HypothesisInput(
            hypothesis_id="H2", statement="Traffic loss reduced revenue",
            supporting_evidence_ids=("E2",), contradicting_evidence_ids=("E4",),
            falsification_checks=(
                FalsificationCheck(check_id="FC2", description="Compare traffic", outcome="falsified", evidence_ids=("E4",)),
            ),
        ),
        HypothesisInput(hypothesis_id="H3", statement="Pricing changed revenue"),
    )
    report = investigate_root_cause(request(hypotheses=hypotheses))

    assert [item.status for item in report.hypotheses] == ["supported", "rejected", "unresolved"]
    assert report.conclusion.determination == "mathematical_driver_identified"
    assert "causal root cause is not established" in report.conclusion.statement


def test_high_strength_causal_evidence_can_pass_causal_gate():
    hypothesis = HypothesisInput(
        hypothesis_id="H1", statement="Checkout failures reduced revenue",
        supporting_evidence_ids=("E2", "E4"), mechanism_evidence_ids=("E3",),
        falsification_checks=(
            FalsificationCheck(check_id="FC1", description="Randomized recovery test", outcome="survived", evidence_ids=("E3",)),
        ),
    )
    report = investigate_root_cause(request(evidence=evidence(causal=True), hypotheses=(hypothesis,)))

    assert report.hypotheses[0].status == "supported"
    assert report.hypotheses[0].causal_evidence_present is True
    assert report.conclusion.determination == "causal_root_cause_supported"
    assert report.conclusion.causal_claim_allowed is True


def test_blocking_data_failure_forces_abstention():
    health = (
        DataHealthCheck(
            check_id="DH1", name="Freshness", status="fail", blocking=True,
            detail="Comparison period is incomplete", evidence_ids=("E1",),
        ),
    )
    report = investigate_root_cause(request(data_health_checks=health))

    assert report.data_health.status == "fail"
    assert report.conclusion.determination == "inconclusive"
    assert report.conclusion.statement == "I cannot determine the root cause from the available evidence."
    assert "data-health" in report.conclusion.abstention_reason


def test_unexplained_residual_is_preserved_and_forces_abstention():
    drivers = (
        DriverInput(driver_id="D1", name="Measured segment", baseline_value=600, comparison_value=540, evidence_ids=("E2",)),
    )
    report = investigate_root_cause(request(drivers=drivers))

    assert report.reconciliation.unexplained_change == -40
    assert report.reconciliation.unexplained_pct == 40
    assert report.reconciliation.residual_within_tolerance is False
    assert report.conclusion.determination == "inconclusive"
    assert any("residual movement" in item for item in report.next_investigations)


def test_overlapping_drivers_are_not_added_together():
    report = investigate_root_cause(request(drivers_form_partition=False))

    assert report.reconciliation.reconcilable is False
    assert report.reconciliation.explained_change is None
    assert report.conclusion.determination == "inconclusive"


def test_zero_baseline_uses_absolute_change_without_inventing_percentage():
    incident = IncidentInput(
        metric="orders", baseline_period="2026-01", comparison_period="2026-02",
        baseline_value=0, comparison_value=10, evidence_ids=("E1",),
    )
    drivers = (DriverInput(driver_id="D1", name="New channel", baseline_value=0, comparison_value=10, evidence_ids=("E2", "E4")),)
    report = investigate_root_cause(request(incident=incident, drivers=drivers))

    assert report.incident.percent_change is None
    assert any("baseline value is zero" in item for item in report.limitations)


def test_unknown_evidence_reference_fails_contract_validation():
    with pytest.raises(ValidationError, match="unknown evidence"):
        request(
            drivers=(
                DriverInput(driver_id="D1", name="Unknown", baseline_value=2, comparison_value=1, evidence_ids=("E99",)),
            )
        )


def test_conclusive_falsification_check_requires_evidence():
    with pytest.raises(ValidationError, match="must cite evidence"):
        FalsificationCheck(check_id="FC1", description="Attempt to disprove", outcome="falsified")


def test_dataframe_boundary_returns_json_ready_report_without_db():
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-02-01", "2026-02-01"],
            "segment": ["Enterprise", "SMB", "Enterprise", "SMB"],
            "revenue": [600.0, 400.0, 510.0, 390.0],
        }
    )
    result = build_root_cause_report(
        frame,
        RCASemanticDefinition(
            metric_name="revenue", metric_column="revenue", time_column="date", driver_column="segment"
        ),
        state={"period_completeness_confirmed": True},
    )

    assert result["incident"]["absolute_change"] == -100.0
    assert result["drivers"][0]["name"] == "Enterprise"
    assert result["reconciliation"]["residual_within_tolerance"] is True
    assert result["conclusion"]["determination"] == "mathematical_driver_identified"


def test_dataframe_boundary_abstains_when_latest_period_is_incomplete():
    frame = pd.DataFrame(
        {"date": ["2026-01-01", "2026-02-01"], "segment": ["A", "A"], "value": [10.0, 5.0]}
    )
    result = build_root_cause_report(
        frame,
        {"metric_name": "value", "metric_column": "value", "time_column": "date", "driver_column": "segment"},
        state={"period_completeness_confirmed": False},
    )

    assert result["data_health"]["status"] == "fail"
    assert result["conclusion"]["determination"] == "inconclusive"
