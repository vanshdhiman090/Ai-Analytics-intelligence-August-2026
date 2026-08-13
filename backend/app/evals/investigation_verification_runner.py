"""Answer-keyed diagnostics for bounded explanation self-falsification."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent


def _rows_from_changes(cells):
    rows = []
    for country, device, channel, change in cells:
        rows.extend(
            [
                {"date": "2026-01-01", "country": country, "device": device, "channel": channel, "revenue": 200.0},
                {"date": "2026-02-01", "country": country, "device": device, "channel": channel, "revenue": 200.0 + change},
            ]
        )
    return rows


def _robust_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Paid", -27),
            ("Germany", "Desktop", "Organic", -27),
            ("Germany", "Tablet", "Partner", -26),
            ("France", "Mobile", "Organic", -4),
            ("France", "Desktop", "Partner", -4),
            ("France", "Tablet", "Paid", -4),
            ("UK", "Mobile", "Partner", -3),
            ("UK", "Desktop", "Paid", -3),
            ("UK", "Tablet", "Organic", -2),
        ]
    )


def _competing_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Paid", -60),
            ("Germany", "Desktop", "Organic", -10),
            ("Germany", "Tablet", "Partner", -10),
            ("France", "Mobile", "Partner", -10),
            ("UK", "Desktop", "Paid", -10),
        ]
    )


def _remainder_rows():
    cells = []
    for country, change in (("Germany", -9), ("France", -6), ("UK", -5)):
        for index in range(5):
            cells.append((country, f"D{index}", f"C{index}", change))
    return _rows_from_changes(cells)


def _offset_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Paid", -50),
            ("Germany", "Desktop", "Organic", -40),
            ("Germany", "Tablet", "Partner", -40),
            ("France", "Mobile", "Organic", 10),
            ("France", "Desktop", "Partner", 10),
            ("France", "Tablet", "Paid", 10),
        ]
    )


def _add_group(rows, period, country, device, count, total):
    value = total / count
    for _ in range(count):
        rows.append(
            {
                "date": f"{period}-01",
                "country": country,
                "device": device,
                "channel": device,
                "revenue": value,
            }
        )


def _scope_quality_rows():
    rows = []
    for device, count, total in (("Mobile", 4, 70), ("Desktop", 3, 70), ("Tablet", 3, 60)):
        _add_group(rows, "2026-01", "Germany", device, count, total)
    for device, count, total in (("Mobile", 2, 35), ("Desktop", 2, 35), ("Tablet", 1, 30)):
        _add_group(rows, "2026-02", "Germany", device, count, total)
    for device, count, total in (("Mobile", 4, 70), ("Desktop", 3, 70), ("Tablet", 3, 60)):
        _add_group(rows, "2026-01", "France", device, count, total)
    for device, total in (("Mobile", 66), ("Desktop", 66), ("Tablet", 58)):
        _add_group(rows, "2026-02", "France", device, 5, total)
    return rows


def _unsafe_global_rows():
    rows = []
    _add_group(rows, "2026-01", "Germany", "Mobile", 10, 200)
    _add_group(rows, "2026-02", "Germany", "Mobile", 2, 100)
    return rows


_DATASETS = {
    "robust": _robust_rows,
    "competing": _competing_rows,
    "remainder": _remainder_rows,
    "offset": _offset_rows,
    "scope_quality": _scope_quality_rows,
    "unsafe_global": _unsafe_global_rows,
}


def _hypothesis_planner(_, output_type):
    return output_type.model_validate(
        {
            "proposals": [
                {"target_dimension": "country", "reason_code": "kpi_relevance"},
                {"target_dimension": "device", "reason_code": "business_structure"},
                {"target_dimension": "channel", "reason_code": "potential_explanatory_value"},
            ]
        }
    )


def _controller(prompt, output_type):
    available = prompt.split("Available untested dimensions:")[1].splitlines()[0]
    for dimension in ("country", "device", "channel"):
        if f'"{dimension}"' in available:
            return output_type.model_validate(
                {
                    "action": "test_dimension",
                    "target_dimension": dimension,
                    "reason_code": "resolve_remaining_uncertainty",
                }
            )
    return output_type.model_validate(
        {"action": "stop", "reason_code": "no_useful_test_remaining"}
    )


def _challenge_planner(mode):
    def generate(_, output_type):
        if mode == "failure":
            raise RuntimeError("fixture challenge provider failure")
        return output_type.model_validate(
            {
                "proposals": [
                    {"challenge_type": "competing_driver", "reason_code": "compare_tested_decompositions"},
                    {"challenge_type": "leading_segment_remainder", "reason_code": "assess_leading_segment_coverage"},
                    {"challenge_type": "offset_cancellation", "reason_code": "assess_opposing_offsets"},
                    {"challenge_type": "data_quality", "reason_code": "assess_target_scope_health"},
                ]
            }
        )

    return generate


def _request(case):
    return {
        "investigation_id": case["id"],
        "goal": "Investigate the revenue decline",
        "kpi": {
            "metric_name": "Revenue",
            "metric_column": "revenue",
            "time_column": "date",
            "aggregation": "sum",
            "time_grain": "month",
        },
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "device", "channel"],
        "hypothesis_planning_enabled": True,
        "evidence_driven_control_enabled": True,
        "self_falsification_enabled": True,
        "maximum_depth": case.get("maximum_depth", 1),
        "minimum_rows_per_period_for_drill_down": 1,
    }


def run_benchmark(cases_path: Path | None = None) -> dict[str, object]:
    cases_path = cases_path or Path(__file__).resolve().parents[2] / "evals" / "investigation_verification_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for case in cases:
            csv_path = Path(directory) / f"{case['id']}.csv"
            pd.DataFrame(_DATASETS[case["dataset"]]()).to_csv(csv_path, index=False)
            with (
                patch("app.services.hypothesis_planner.generate_structured", _hypothesis_planner),
                patch("app.services.investigation_controller.generate_structured", _controller),
                patch("app.services.investigation_verifier.generate_structured", _challenge_planner(case["provider_mode"])),
            ):
                state = RootCauseAgent().execute(
                    {"cleaned_path": str(csv_path), "investigation_request": _request(case)}
                )["investigation_state"]
            expected = case["expected"]
            passed = all(state.get(key) == value for key, value in expected.items() if key in {"outcome", "leading_dimension", "leading_segment", "verification_status"})
            codes = {item["result_code"] for item in state["verification_records"]}
            if "required_result_code" in expected:
                passed = passed and expected["required_result_code"] in codes
            planning = state.get("challenge_planning_record")
            if "fallback_reason" in expected:
                passed = passed and planning and planning["fallback_reason"] == expected["fallback_reason"]
            if "downstream_stopping_reason" in expected:
                downstream = [item for item in state["investigation_path"] if item["depth"] > 0]
                passed = passed and any(item["stopping_reason"] == expected["downstream_stopping_reason"] for item in downstream)
                passed = passed and state["leading_dimension"] == "country" and state["leading_segment"] == "Germany"
            test_ids = {item["test_id"] for item in state["tests_executed"]}
            evidence_ids = {item["evidence_id"] for item in state["evidence"]}
            verification_ids = {item["verification_id"] for item in state["verification_records"]}
            references_resolve = all(set(item["source_test_ids"]).issubset(test_ids) and set(item["source_evidence_ids"]).issubset(evidence_ids) for item in state["verification_records"])
            classified = set((*state["supporting_verification_ids"], *state["contradicting_verification_ids"], *state["unresolved_verification_ids"]))
            references_resolve = references_resolve and classified == verification_ids
            challenge_types = [item["challenge_type"] for item in state["verification_records"]]
            duplicate_count = len(challenge_types) - len(set(challenge_types))
            passed = passed and references_resolve and duplicate_count == 0
            results.append(
                {
                    "id": case["id"],
                    "paired_group": case.get("paired_group"),
                    "passed": passed,
                    "outcome": state["outcome"],
                    "leading_dimension": state["leading_dimension"],
                    "leading_segment": state["leading_segment"],
                    "verification_status": state["verification_status"],
                    "challenge_count": len(challenge_types),
                    "llm_challenges": sum(item["source"] == "llm" for item in (planning or {}).get("validated_challenges", [])),
                    "fallback_challenges": sum(item["source"] == "deterministic_fallback" for item in (planning or {}).get("validated_challenges", [])),
                    "provider_failure": bool(planning and planning["fallback_reason"] == "provider_failure"),
                    "contradiction_count": len(state["contradicting_verification_ids"]),
                    "duplicate_challenge_execution_count": duplicate_count,
                    "references_resolve": references_resolve,
                }
            )
    paired = [item for item in results if item["paired_group"] == "verification-reactivity"]
    paired_pass = len(paired) == 2 and paired[0]["leading_dimension"] == paired[1]["leading_dimension"] and paired[0]["leading_segment"] == paired[1]["leading_segment"] and paired[0]["verification_status"] != paired[1]["verification_status"]
    planned = [item for item in results if item["challenge_count"]]
    total_challenges = sum(item["challenge_count"] for item in planned)
    contradiction_cases = {"near_equal_competing_decomposition", "large_leading_segment_remainder", "material_offset_cancellation"}
    clean_cases = {"leader_survives", "challenge_provider_failure", "downstream_scope_quality_is_local"}
    metrics = {
        "challenge_validation_rate": sum(item["llm_challenges"] for item in planned) / total_challenges if total_challenges else 1.0,
        "fallback_rate": sum(item["fallback_challenges"] for item in planned) / total_challenges if total_challenges else 0.0,
        "average_challenges_per_investigation": total_challenges / len(results),
        "contradiction_detection_rate": sum(item["id"] in contradiction_cases and item["contradiction_count"] > 0 for item in results) / len(contradiction_cases),
        "false_contradiction_rate": sum(item["id"] in clean_cases and item["contradiction_count"] > 0 for item in results) / len(clean_cases),
        "abstention_correctness": next(item["outcome"] == "data_quality_incident" and item["verification_status"] == "not_run" for item in results if item["id"] == "unsafe_global_data_stops_before_verification"),
        "provider_failure_recovery_rate": next(item["passed"] for item in results if item["id"] == "challenge_provider_failure"),
        "paired_verification_reactivity_passed": paired_pass,
        "duplicate_challenge_execution_count": sum(item["duplicate_challenge_execution_count"] for item in results),
        "verification_reference_resolution_rate": sum(item["references_resolve"] for item in results) / len(results),
    }
    return {
        "total": len(results),
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "verification_metrics": metrics,
        "release_ready": all(item["passed"] for item in results) and paired_pass,
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
