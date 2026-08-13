"""Answer-keyed engineering diagnostics for the bounded investigation loop."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent


def _planner(_, output_type):
    return output_type.model_validate({"proposals": [
        {"target_dimension":"country","reason_code":"kpi_relevance"},
        {"target_dimension":"device","reason_code":"business_structure"},
        {"target_dimension":"channel","reason_code":"potential_explanatory_value"},
    ]})


def _action(output_type, dimension=None, *, stop=False):
    return output_type.model_validate({"action":"stop" if stop else "test_dimension", "target_dimension":dimension, "reason_code":"no_useful_test_remaining" if stop else "resolve_remaining_uncertainty"})


def _strong_rows():
    return [
        {"date":"2026-01-01","country":"Germany","device":"Mobile","channel":"Paid","revenue":300},{"date":"2026-02-01","country":"Germany","device":"Mobile","channel":"Paid","revenue":260},
        {"date":"2026-01-01","country":"Germany","device":"Desktop","channel":"Organic","revenue":300},{"date":"2026-02-01","country":"Germany","device":"Desktop","channel":"Organic","revenue":260},
        {"date":"2026-01-01","country":"France","device":"Mobile","channel":"Paid","revenue":100},{"date":"2026-02-01","country":"France","device":"Mobile","channel":"Paid","revenue":125},
        {"date":"2026-01-01","country":"France","device":"Desktop","channel":"Organic","revenue":100},{"date":"2026-02-01","country":"France","device":"Desktop","channel":"Organic","revenue":125},
        {"date":"2026-01-01","country":"UK","device":"Mobile","channel":"Organic","revenue":100},{"date":"2026-02-01","country":"UK","device":"Mobile","channel":"Organic","revenue":65},
        {"date":"2026-01-01","country":"UK","device":"Desktop","channel":"Paid","revenue":100},{"date":"2026-02-01","country":"UK","device":"Desktop","channel":"Paid","revenue":65},
    ]


def _weak_rows():
    rows = []
    for index in range(10):
        rows.extend([
            {"date":"2026-01-01","country":f"C{index}","device":"Mobile" if index < 6 else "Desktop","channel":"Paid" if index % 2 else "Organic","revenue":100},
            {"date":"2026-02-01","country":f"C{index}","device":"Mobile" if index < 6 else "Desktop","channel":"Paid" if index % 2 else "Organic","revenue":90},
        ])
    return rows


def _recursive_rows():
    rows = []
    for country, device, channel, before, after in [("Germany","Mobile","Paid",300,220),("Germany","Desktop","Organic",200,180),("France","Mobile","Paid",100,95)]:
        for _ in range(5):
            rows.extend([{"date":"2026-01-01","country":country,"device":device,"channel":channel,"revenue":before/5},{"date":"2026-02-01","country":country,"device":device,"channel":channel,"revenue":after/5}])
    return rows


def _controller(case):
    count = 0
    def generate(prompt, output_type):
        nonlocal count
        count += 1
        mode = case["controller_mode"]
        if mode == "reactive":
            if count == 1:
                return _action(output_type, "country")
            if count == 2:
                return _action(output_type, "device" if '\"status\": \"supported\"' in prompt else "channel")
            available = prompt.split("Available untested dimensions:")[1].splitlines()[0]
            return _action(output_type, "channel" if '"channel"' in available else "device")
        if mode == "repeated":
            return _action(output_type, "country" if count <= 2 else "channel")
        if mode == "invalid":
            return _action(output_type, "marketing_campaign" if count == 1 else ("device" if count == 2 else "channel"))
        if mode == "provider_mid":
            if count == 2:
                raise RuntimeError("fixture provider failure")
            return _action(output_type, "country" if count == 1 else "channel")
        if mode == "premature_stop":
            return _action(output_type, stop=True)
        if mode == "scope":
            available = prompt.split("Available untested dimensions:")[1].splitlines()[0]
            for dimension in ("country", "device", "channel"):
                if f'"{dimension}"' in available:
                    return _action(output_type, dimension)
        raise RuntimeError("unsupported fixture mode")
    return generate


def run_benchmark(cases_path: Path | None = None) -> dict[str, object]:
    cases_path = cases_path or Path(__file__).resolve().parents[2] / "evals" / "investigation_controller_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for case in cases:
            rows = _weak_rows() if case.get("dataset") == "weak" else _recursive_rows() if case.get("dataset") == "recursive" else _strong_rows()
            csv_path = Path(directory) / f"{case['id']}.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            request = {"investigation_id":case["id"],"goal":"Investigate revenue decline","kpi":{"metric_name":"Revenue","metric_column":"revenue","time_column":"date","aggregation":"sum","time_grain":"month"},"baseline_period":"2026-01","comparison_period":"2026-02","candidate_dimensions":["country","device","channel"],"hypothesis_planning_enabled":True,"evidence_driven_control_enabled":True,"maximum_depth":case.get("maximum_depth",1),"minimum_rows_per_period_for_drill_down":1}
            with patch("app.services.hypothesis_planner.generate_structured", _planner), patch("app.services.investigation_controller.generate_structured", _controller(case)):
                state = RootCauseAgent().execute({"cleaned_path":str(csv_path),"investigation_request":request})["investigation_state"]
            iterations = state["investigation_iterations"]
            identities = [(tuple((part["dimension"],part["segment"]) for part in item["filter_path"]),item["executed_dimension"]) for item in iterations if item["executed_action"] == "test_dimension"]
            expected = case["expected"]
            actual_second = iterations[1]["executed_dimension"] if len(iterations) > 1 else None
            passed = state["leading_dimension"] == expected["leading_dimension"] and ("second_dimension" not in expected or actual_second == expected["second_dimension"])
            if "required_rejection" in expected:
                passed = passed and any(item["rejection_reason"] == expected["required_rejection"] for item in iterations)
            evidence_ids = {item["evidence_id"] for item in state["evidence"]}
            refs_resolve = all(item["evidence_id"] in evidence_ids for item in iterations if item["evidence_id"])
            ceiling = sum(3-depth for depth in range(min(3, case.get("maximum_depth",1))))
            results.append({"id":case["id"],"paired_group":case.get("paired_group"),"passed":passed and refs_resolve and len(identities)==len(set(identities)) and len(identities)<=ceiling,"first_dimension":iterations[0]["executed_dimension"],"second_dimension":actual_second,"iteration_count":len(iterations),"test_count":len(state["tests_executed"]),"valid_actions":sum(item["validation_status"]=="accepted" for item in iterations),"fallbacks":sum(item["fallback_used"] for item in iterations),"repeated_rejections":sum(item["rejection_reason"]=="dimension_already_tested_in_scope" for item in iterations),"invalid_dimension_rejections":sum(item["rejection_reason"]=="dimension_not_allowed" for item in iterations),"premature_stop_rejections":sum(item["rejection_reason"]=="premature_stop" for item in iterations),"provider_failures":sum(item["rejection_reason"]=="provider_failure" for item in iterations),"duplicate_executed_tests":len(identities)-len(set(identities)),"root_scope_sufficient":len([item for item in identities if item[0]==()])==3})
    paired = [item for item in results if item["paired_group"] == "evidence-reactivity"]
    reactive_pass = len(paired)==2 and paired[0]["first_dimension"]==paired[1]["first_dimension"] and paired[0]["second_dimension"]!=paired[1]["second_dimension"]
    total_iterations = sum(item["iteration_count"] for item in results)
    provider_cases = sum(item["provider_failures"]>0 for item in results)
    metrics = {"valid_action_rate":sum(item["valid_actions"] for item in results)/total_iterations,"fallback_rate":sum(item["fallbacks"] for item in results)/total_iterations,"repeated_action_rejection_count":sum(item["repeated_rejections"] for item in results),"invalid_dimension_rejection_count":sum(item["invalid_dimension_rejections"] for item in results),"premature_stop_rejection_count":sum(item["premature_stop_rejections"] for item in results),"average_deterministic_tests_per_investigation":sum(item["test_count"] for item in results)/len(results),"provider_failure_recovery_rate":sum(item["provider_failures"]>0 and item["passed"] for item in results)/provider_cases if provider_cases else 1.0,"completed_scope_sufficiency_rate":sum(item["root_scope_sufficient"] for item in results)/len(results),"duplicate_executed_test_count":sum(item["duplicate_executed_tests"] for item in results),"evidence_reactive_paired_case_passed":reactive_pass}
    return {"total":len(results),"passed":sum(item["passed"] for item in results),"failed":sum(not item["passed"] for item in results),"controller_metrics":metrics,"release_ready":all(item["passed"] for item in results) and reactive_pass,"results":results}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
