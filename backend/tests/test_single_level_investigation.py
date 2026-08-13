import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.services.root_cause import run_single_level_investigation


def request(**overrides):
    value = {
        "investigation_id": "test-1",
        "goal": "Investigate the revenue decline",
        "kpi": {"metric_name": "Revenue", "metric_column": "revenue", "time_column": "date", "aggregation": "sum", "time_grain": "month", "unit": "EUR"},
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "channel"],
    }
    value.update(overrides)
    return value


def driver_frame():
    return pd.DataFrame([
        {"date": "2026-01-01", "country": "Germany", "channel": "Online", "revenue": 300},
        {"date": "2026-01-01", "country": "Germany", "channel": "Retail", "revenue": 300},
        {"date": "2026-01-01", "country": "France", "channel": "Online", "revenue": 100},
        {"date": "2026-01-01", "country": "France", "channel": "Retail", "revenue": 100},
        {"date": "2026-01-01", "country": "UK", "channel": "Online", "revenue": 100},
        {"date": "2026-01-01", "country": "UK", "channel": "Retail", "revenue": 100},
        {"date": "2026-02-01", "country": "Germany", "channel": "Online", "revenue": 260},
        {"date": "2026-02-01", "country": "Germany", "channel": "Retail", "revenue": 260},
        {"date": "2026-02-01", "country": "France", "channel": "Online", "revenue": 125},
        {"date": "2026-02-01", "country": "France", "channel": "Retail", "revenue": 125},
        {"date": "2026-02-01", "country": "UK", "channel": "Online", "revenue": 65},
        {"date": "2026-02-01", "country": "UK", "channel": "Retail", "revenue": 65},
    ])


def test_leading_contributor_is_a_segment_and_preserves_offsets():
    state = run_single_level_investigation(driver_frame(), request())

    assert state.outcome == "strongest_supported_driver"
    assert (state.leading_dimension, state.leading_segment) == ("country", "Germany")
    assert state.leading_signed_contribution == -80
    assert state.leading_contribution_to_net_change_pct == 80
    assert state.net_kpi_movement == -100
    assert state.downward_pressure == -150
    assert state.positive_offset == 50
    assert state.unexplained_movement == -20
    assert state.evidence_strength == "strong"
    country = next(test for test in state.tests_executed if test.dimension == "country")
    assert country.net_dimension_change == state.net_kpi_movement
    assert country.reconciles_to_kpi_change


def test_unsafe_current_period_is_detected_from_nulls_not_input_flag():
    frame = pd.DataFrame([
        {"date": "2026-01-01", "country": "Germany", "revenue": 50},
        {"date": "2026-01-01", "country": "France", "revenue": 50},
        {"date": "2026-02-01", "country": "Germany", "revenue": 40},
        {"date": "2026-02-01", "country": "France", "revenue": None},
    ])
    state = run_single_level_investigation(frame, request(candidate_dimensions=["country"]))
    assert state.outcome == "data_quality_incident"
    assert any(check.name == "Comparison metric completeness" and check.blocking for check in state.data_health)
    assert not state.tests_executed


def test_no_material_segment_abstains():
    rows = []
    for index in range(10):
        rows.extend([
            {"date": "2026-01-01", "region": f"R{index}", "revenue": 100},
            {"date": "2026-02-01", "region": f"R{index}", "revenue": 90},
        ])
    state = run_single_level_investigation(pd.DataFrame(rows), request(candidate_dimensions=["region"]))
    assert state.outcome == "inconclusive"
    assert state.evidence_strength == "weak"
    assert all(item.status == "weak" for item in state.hypotheses)


def test_strength_thresholds_are_deterministic():
    def state_for_share(share):
        rows = [
            {"date": "2026-01-01", "country": "A", "revenue": 100},
            {"date": "2026-02-01", "country": "A", "revenue": 100 - share},
        ]
        for index in range(10):
            movement = (100 - share) / 10
            rows.extend([
                {"date": "2026-01-01", "country": f"B{index}", "revenue": 100},
                {"date": "2026-02-01", "country": f"B{index}", "revenue": 100 - movement},
            ])
        return run_single_level_investigation(pd.DataFrame(rows), request(candidate_dimensions=["country"]))
    assert state_for_share(50).evidence_strength == "strong"
    assert state_for_share(20).evidence_strength == "moderate"
    assert state_for_share(5).evidence_strength == "weak"


def test_root_cause_agent_uses_real_deterministic_investigation_path(tmp_path, monkeypatch):
    path = tmp_path / "revenue.csv"
    driver_frame().to_csv(path, index=False)
    monkeypatch.setattr("app.agent.subagents.root_cause_agent.AnalyzeAgent.run_analysis", lambda *_: (_ for _ in ()).throw(AssertionError("LLM path must not run")))
    result = RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": request()})
    assert result["investigation_state"]["leading_segment"] == "Germany"
