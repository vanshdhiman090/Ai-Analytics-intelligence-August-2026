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


def test_comparison_row_coverage_failure_message_describes_volume_not_missing_days():
    rows = [{"date": "2026-01-01", "country": "Germany", "revenue": 100} for _ in range(10)]
    rows += [{"date": "2026-02-01", "country": "Germany", "revenue": 100} for _ in range(7)]
    state = run_single_level_investigation(pd.DataFrame(rows), request(candidate_dimensions=["country"]))
    assert state.outcome == "data_quality_incident"
    coverage_check = next(check for check in state.data_health if check.name == "Comparison row coverage")
    assert coverage_check.status == "fail"
    assert coverage_check.blocking
    assert coverage_check.detail == "Comparison period has 70% of baseline period's transaction volume; minimum required is 80%."


def test_comparison_row_coverage_pass_fail_threshold_logic_is_unchanged():
    def coverage_check_for(comparison_rows):
        rows = [{"date": "2026-01-01", "country": "Germany", "revenue": 100} for _ in range(10)]
        rows += [{"date": "2026-02-01", "country": "Germany", "revenue": 100} for _ in range(comparison_rows)]
        state = run_single_level_investigation(pd.DataFrame(rows), request(candidate_dimensions=["country"]))
        return next(check for check in state.data_health if check.name == "Comparison row coverage")

    below_threshold = coverage_check_for(7)  # 7/10 = 0.70 < default 0.8
    assert below_threshold.status == "fail"
    assert below_threshold.blocking

    at_threshold = coverage_check_for(8)  # 8/10 = 0.80 == default 0.8, still passes (>=)
    assert at_threshold.status == "pass"
    assert not at_threshold.blocking


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


def _rows_for_recursive_path(*, mobile_null_rows=0):
    leaves = [
        ("Germany", "Mobile", "Returning", 200, 155),
        ("Germany", "Mobile", "New", 100, 85),
        ("Germany", "Desktop", "Returning", 100, 90),
        ("Germany", "Desktop", "New", 100, 90),
        ("France", "Mobile", "Returning", 100, 90),
        ("France", "Mobile", "New", 100, 90),
    ]
    rows = []
    for country, device, customer_type, baseline, comparison in leaves:
        for number in range(5):
            base = {"date": "2026-01-01", "country": country, "device": device, "customer_type": customer_type, "revenue": baseline / 5, "id": f"b-{country}-{device}-{customer_type}-{number}"}
            current = {**base, "date": "2026-02-01", "revenue": comparison / 5, "id": f"c-{country}-{device}-{customer_type}-{number}"}
            rows.extend((base, current))
    for number in range(mobile_null_rows):
        rows.append({"date": "2026-02-01", "country": "Germany", "device": "Mobile", "customer_type": "Returning", "revenue": None, "id": f"null-{number}"})
    return rows


def test_recursive_path_uses_local_and_global_denominators():
    state = run_single_level_investigation(pd.DataFrame(_rows_for_recursive_path()), request(candidate_dimensions=["country", "device", "customer_type"], maximum_depth=3))
    assert [(node.depth, node.selected_dimension, node.selected_segment) for node in state.investigation_path] == [(0, None, None), (1, "country", "Germany"), (2, "device", "Mobile"), (3, "customer_type", "Returning")]
    mobile = state.investigation_path[2]
    assert mobile.parent_kpi_movement == -80
    assert mobile.segment_movement == -60
    assert mobile.local_contribution_pct == 75
    assert mobile.global_contribution_pct == 60
    assert state.investigation_path[-1].stopping_reason == "maximum_depth_reached"


def test_recursive_stops_when_no_child_is_material():
    rows = []
    for index in range(10):
        for number in range(5):
            rows.extend((
                {"date": "2026-01-01", "country": "Germany", "device": f"D{index}", "revenue": 10, "id": f"b-{index}-{number}"},
                {"date": "2026-02-01", "country": "Germany", "device": f"D{index}", "revenue": 8, "id": f"c-{index}-{number}"},
            ))
    for number in range(5):
        rows.extend((
            {"date": "2026-01-01", "country": "France", "device": "F", "revenue": 100, "id": f"fb-{number}"},
            {"date": "2026-02-01", "country": "France", "device": "F", "revenue": 96, "id": f"fc-{number}"},
        ))
    state = run_single_level_investigation(pd.DataFrame(rows), request(candidate_dimensions=["country", "device"], maximum_depth=3))
    assert state.investigation_path[1].selected_segment == "Germany"
    assert state.investigation_path[-1].stopping_reason == "no_material_child_contributor"


def test_recursive_detects_deep_scoped_data_quality_failure():
    state = run_single_level_investigation(pd.DataFrame(_rows_for_recursive_path(mobile_null_rows=5)), request(candidate_dimensions=["country", "device", "customer_type"], maximum_depth=3))
    assert state.investigation_path[-1].selected_segment == "Mobile"
    assert state.investigation_path[-1].stopping_reason == "scoped_data_quality_failure"


def test_missing_dimension_value_reconciles_and_offsets_can_exceed_100_percent():
    frame = pd.DataFrame([
        {"date": "2026-01-01", "country": "Germany", "revenue": 200}, {"date": "2026-02-01", "country": "Germany", "revenue": 70},
        {"date": "2026-01-01", "country": "France", "revenue": 100}, {"date": "2026-02-01", "country": "France", "revenue": 130},
        {"date": "2026-01-01", "country": None, "revenue": 100}, {"date": "2026-02-01", "country": None, "revenue": 100},
        {"date": "2026-01-01", "country": "Tiny", "revenue": 10}, {"date": "2026-02-01", "country": "Tiny", "revenue": 0},
    ])
    state = run_single_level_investigation(frame, request(candidate_dimensions=["country"]))
    contribution_test = state.tests_executed[0]
    assert contribution_test.reconciles_to_kpi_change
    assert any(item.segment == "__MISSING__" for item in contribution_test.segment_contributions)
    assert state.leading_segment == "Germany"
    assert state.leading_contribution_to_net_change_pct == 118.18181818181819
    assert state.positive_offset == 30


def test_maximum_depth_one_preserves_the_single_level_result():
    baseline = run_single_level_investigation(driver_frame(), request())
    bounded = run_single_level_investigation(driver_frame(), request(maximum_depth=1))
    assert bounded.model_dump(exclude={"investigation_path"}) == baseline.model_dump(exclude={"investigation_path"})
    assert bounded.investigation_path == ()


def test_negligible_parent_movement_stops_before_child_percentages():
    state = run_single_level_investigation(pd.DataFrame(_rows_for_recursive_path()), request(candidate_dimensions=["country", "device", "customer_type"], maximum_depth=3, negligible_parent_movement_tolerance=100))
    assert state.investigation_path[-1].selected_segment == "Germany"
    assert state.investigation_path[-1].stopping_reason == "negligible_parent_movement"


def _segment_row_count_frame():
    """Germany: absent from comparison. Austria: fully-null baseline metric.
    France: normal real data in both periods (control)."""
    return pd.DataFrame([
        {"date": "2026-01-01", "country": "Germany", "revenue": 100},
        {"date": "2026-01-01", "country": "Germany", "revenue": 100},
        {"date": "2026-01-01", "country": "Austria", "revenue": None},
        {"date": "2026-01-01", "country": "Austria", "revenue": None},
        {"date": "2026-02-01", "country": "Austria", "revenue": 50},
        {"date": "2026-01-01", "country": "France", "revenue": 100},
        {"date": "2026-02-01", "country": "France", "revenue": 40},
    ])


def _assert_segment_row_counts_are_captured(country_test):
    by_segment = {item.segment: item for item in country_test.segment_contributions}

    germany = by_segment["Germany"]
    assert (germany.baseline_row_count, germany.comparison_row_count) == (2, 0)
    assert (germany.baseline_null_metric_row_count, germany.comparison_null_metric_row_count) == (0, 0)
    assert germany.comparison_value == 0  # existing fill_value=0 behaviour is unchanged by Milestone A

    austria = by_segment["Austria"]
    assert (austria.baseline_row_count, austria.comparison_row_count) == (2, 1)
    assert (austria.baseline_null_metric_row_count, austria.comparison_null_metric_row_count) == (2, 0)
    assert austria.baseline_value == 0  # existing fill_value=0 behaviour is unchanged by Milestone A

    france = by_segment["France"]
    assert (france.baseline_row_count, france.comparison_row_count) == (1, 1)
    assert (france.baseline_null_metric_row_count, france.comparison_null_metric_row_count) == (0, 0)
    assert (france.baseline_value, france.comparison_value) == (100, 40)


def test_segment_row_counts_are_captured_in_the_plain_investigation_path():
    state = run_single_level_investigation(
        _segment_row_count_frame(),
        request(candidate_dimensions=["country"], comparison_coverage_ratio=0.01),
    )
    country_test = next(test for test in state.tests_executed if test.dimension == "country")
    _assert_segment_row_counts_are_captured(country_test)


def test_segment_row_counts_are_captured_in_the_evidence_driven_path():
    state = run_single_level_investigation(
        _segment_row_count_frame(),
        request(candidate_dimensions=["country"], comparison_coverage_ratio=0.01, evidence_driven_control_enabled=True),
    )
    country_test = next(test for test in state.tests_executed if test.dimension == "country")
    _assert_segment_row_counts_are_captured(country_test)
