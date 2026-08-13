import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.domain.root_cause_contracts import HypothesisProposalSet, NextTestActionProposal


def request(**overrides):
    values = {
        "investigation_id": "controller-test",
        "goal": "Investigate revenue decline",
        "kpi": {"metric_name": "Revenue", "metric_column": "revenue", "time_column": "date", "aggregation": "sum", "time_grain": "month"},
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "device", "channel"],
        "hypothesis_planning_enabled": True,
        "evidence_driven_control_enabled": True,
        "maximum_depth": 1,
    }
    values.update(overrides)
    return values


def planner(_, output_type):
    assert output_type is HypothesisProposalSet
    return output_type.model_validate({"proposals": [
        {"target_dimension": "country", "reason_code": "kpi_relevance"},
        {"target_dimension": "device", "reason_code": "business_structure"},
        {"target_dimension": "channel", "reason_code": "potential_explanatory_value"},
    ]})


def action(dimension=None, *, stop=False):
    return NextTestActionProposal(action="stop" if stop else "test_dimension", target_dimension=dimension, reason_code="no_useful_test_remaining" if stop else "resolve_remaining_uncertainty")


def frame():
    return pd.DataFrame([
        {"date":"2026-01-01","country":"Germany","device":"Mobile","channel":"Paid","revenue":300},
        {"date":"2026-02-01","country":"Germany","device":"Mobile","channel":"Paid","revenue":220},
        {"date":"2026-01-01","country":"France","device":"Desktop","channel":"Organic","revenue":200},
        {"date":"2026-02-01","country":"France","device":"Desktop","channel":"Organic","revenue":180},
    ])


def run_agent(tmp_path, monkeypatch, controller, *, data=None, overrides=None):
    path = tmp_path / "controlled.csv"
    (data if data is not None else frame()).to_csv(path, index=False)
    monkeypatch.setattr("app.services.hypothesis_planner.generate_structured", planner)
    monkeypatch.setattr("app.services.investigation_controller.generate_structured", controller)
    return RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": request(**(overrides or {}))})["investigation_state"]


def test_one_test_per_iteration_and_repeated_action_falls_back(tmp_path, monkeypatch):
    calls = iter((action("country"), action("country"), action("channel")))
    result = run_agent(tmp_path, monkeypatch, lambda *_: next(calls))
    iterations = result["investigation_iterations"]
    assert [item["executed_dimension"] for item in iterations] == ["country", "device", "channel"]
    assert iterations[1]["rejection_reason"] == "dimension_already_tested_in_scope"
    assert iterations[1]["fallback_used"] is True
    assert len(result["tests_executed"]) == len(iterations) == 3
    assert len({(tuple((part["dimension"], part["segment"]) for part in item["filter_path"]), item["executed_dimension"]) for item in iterations}) == 3
    evidence_ids = {item["evidence_id"] for item in result["evidence"]}
    assert all(item["evidence_id"] in evidence_ids for item in iterations)


def test_invalid_dimension_and_premature_stop_use_safe_fallback(tmp_path, monkeypatch):
    calls = iter((action("marketing_campaign"), action(stop=True), action("channel")))
    result = run_agent(tmp_path, monkeypatch, lambda *_: next(calls))
    iterations = result["investigation_iterations"]
    assert iterations[0]["rejection_reason"] == "dimension_not_allowed"
    assert iterations[1]["rejection_reason"] == "premature_stop"
    assert result["outcome"] == "strongest_supported_driver"
    assert len(result["tests_executed"]) == 3


def test_provider_failure_mid_loop_recovers(tmp_path, monkeypatch):
    count = 0
    def controller(*_):
        nonlocal count
        count += 1
        if count == 1:
            return action("country")
        if count == 2:
            raise RuntimeError("provider unavailable")
        return action("channel")
    result = run_agent(tmp_path, monkeypatch, controller)
    assert result["investigation_iterations"][1]["rejection_reason"] == "provider_failure"
    assert result["investigation_iterations"][1]["fallback_used"] is True
    assert len(result["tests_executed"]) == 3


def test_same_prior_different_evidence_changes_second_action(tmp_path, monkeypatch):
    strong = frame()
    weak_rows = []
    for index in range(6):
        weak_rows.extend([
            {"date":"2026-01-01","country":f"C{index}","device":"Mobile" if index < 3 else "Desktop","channel":"Paid" if index % 2 else "Organic","revenue":100},
            {"date":"2026-02-01","country":f"C{index}","device":"Mobile" if index < 3 else "Desktop","channel":"Paid" if index % 2 else "Organic","revenue":90},
        ])
    weak = pd.DataFrame(weak_rows)

    def reactive_controller():
        count = 0
        def generate(prompt, _):
            nonlocal count
            count += 1
            if count == 1:
                return action("country")
            if count == 2:
                return action("device" if '"status": "supported"' in prompt else "channel")
            return action("channel" if '"device"' not in prompt.split("Already tested in this exact scope:")[-1].splitlines()[0] else "device")
        return generate

    result_a = run_agent(tmp_path, monkeypatch, reactive_controller(), data=strong)
    result_b = run_agent(tmp_path, monkeypatch, reactive_controller(), data=weak)
    assert result_a["investigation_iterations"][0]["executed_dimension"] == "country"
    assert result_b["investigation_iterations"][0]["executed_dimension"] == "country"
    assert result_a["investigation_iterations"][1]["executed_dimension"] == "device"
    assert result_b["investigation_iterations"][1]["executed_dimension"] == "channel"
    assert result_a["investigation_iterations"][1]["known_test_ids"]
    assert result_b["investigation_iterations"][1]["known_test_ids"]


def test_scope_transition_allows_new_scope_dimension_identity(tmp_path, monkeypatch):
    rows = []
    leaves = [("Germany","Mobile","Paid",300,220),("Germany","Desktop","Organic",200,180),("France","Mobile","Paid",100,95)]
    for country, device, channel, before, after in leaves:
        for index in range(5):
            rows.extend([
                {"date":"2026-01-01","country":country,"device":device,"channel":channel,"revenue":before/5},
                {"date":"2026-02-01","country":country,"device":device,"channel":channel,"revenue":after/5},
            ])
    def controller(prompt, _):
        if "Available untested dimensions" in prompt:
            if '"country"' in prompt.split("Available untested dimensions:")[1].splitlines()[0]:
                return action("country")
            if '"device"' in prompt.split("Available untested dimensions:")[1].splitlines()[0]:
                return action("device")
        return action("channel")
    result = run_agent(tmp_path, monkeypatch, controller, data=pd.DataFrame(rows), overrides={"maximum_depth": 2})
    identities = [(tuple((item["dimension"], item["segment"]) for item in iteration["filter_path"]), iteration["executed_dimension"]) for iteration in result["investigation_iterations"]]
    assert ((), "device") in identities
    assert ((('country', 'Germany'),), "device") in identities
    assert len(identities) <= 3 + 2


def test_controller_disabled_is_semantically_equivalent(tmp_path, monkeypatch):
    path = tmp_path / "baseline.csv"; frame().to_csv(path, index=False)
    base_request = request(evidence_driven_control_enabled=False, hypothesis_planning_enabled=False)
    explicit_request = {**base_request, "evidence_driven_control_enabled": False}
    first = RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": base_request})["investigation_state"]
    second = RootCauseAgent().execute({"cleaned_path": str(path), "investigation_request": explicit_request})["investigation_state"]
    keys = ("outcome", "leading_dimension", "leading_segment", "leading_signed_contribution", "leading_contribution_to_net_change_pct", "investigation_path", "stopping_reason")
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}


def test_controller_order_cannot_change_mathematical_driver(tmp_path, monkeypatch):
    first_order = iter((action("country"), action("device"), action("channel")))
    first = run_agent(tmp_path, monkeypatch, lambda *_: next(first_order))
    second_order = iter((action("channel"), action("device"), action("country")))
    second = run_agent(tmp_path, monkeypatch, lambda *_: next(second_order))
    keys = ("leading_dimension", "leading_segment", "leading_signed_contribution", "leading_contribution_to_net_change_pct")
    assert {key: first[key] for key in keys} == {key: second[key] for key in keys}
    assert [item["executed_dimension"] for item in first["investigation_iterations"]] != [item["executed_dimension"] for item in second["investigation_iterations"]]


def test_malformed_controller_output_falls_back_without_extra_test(tmp_path, monkeypatch):
    count = 0
    def controller(*_):
        nonlocal count
        count += 1
        if count == 1:
            return {"action": "test_dimension", "reason_code": "resolve_remaining_uncertainty"}
        return action("device" if count == 2 else "channel")
    result = run_agent(tmp_path, monkeypatch, controller)
    assert result["investigation_iterations"][0]["rejection_reason"] == "malformed_output"
    assert len(result["investigation_iterations"]) == len(result["tests_executed"]) == 3
