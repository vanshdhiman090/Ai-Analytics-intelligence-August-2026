"""Answer-keyed usefulness signals for bounded hypothesis planning.

These are engineering diagnostics, not a claim that a small fixture suite
measures production reasoning quality.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent


def _simple_rows():
    return [
        {"date": "2026-01-01", "country": "Germany", "device": "Mobile", "customer_type": "Returning", "revenue": 100},
        {"date": "2026-02-01", "country": "Germany", "device": "Mobile", "customer_type": "Returning", "revenue": 40},
        {"date": "2026-01-01", "country": "France", "device": "Desktop", "customer_type": "New", "revenue": 100},
        {"date": "2026-02-01", "country": "France", "device": "Desktop", "customer_type": "New", "revenue": 90},
    ]


def _recursive_rows():
    return [
        {"date":"2026-01-01","country":"Germany","device":"Mobile","customer_type":"Returning","revenue":200},{"date":"2026-02-01","country":"Germany","device":"Mobile","customer_type":"Returning","revenue":155},
        {"date":"2026-01-01","country":"Germany","device":"Mobile","customer_type":"New","revenue":100},{"date":"2026-02-01","country":"Germany","device":"Mobile","customer_type":"New","revenue":85},
        {"date":"2026-01-01","country":"Germany","device":"Desktop","customer_type":"Returning","revenue":100},{"date":"2026-02-01","country":"Germany","device":"Desktop","customer_type":"Returning","revenue":90},
        {"date":"2026-01-01","country":"Germany","device":"Desktop","customer_type":"New","revenue":100},{"date":"2026-02-01","country":"Germany","device":"Desktop","customer_type":"New","revenue":90},
        {"date":"2026-01-01","country":"France","device":"Mobile","customer_type":"Returning","revenue":100},{"date":"2026-02-01","country":"France","device":"Mobile","customer_type":"Returning","revenue":90},
        {"date":"2026-01-01","country":"France","device":"Mobile","customer_type":"New","revenue":100},{"date":"2026-02-01","country":"France","device":"Mobile","customer_type":"New","revenue":90},
    ]


def _request(case):
    return {
        "investigation_id": case["id"], "goal": "Investigate revenue decline",
        "kpi": {"metric_name": "Revenue", "metric_column": "revenue", "time_column": "date", "aggregation": "sum", "time_grain": "month"},
        "baseline_period": "2026-01", "comparison_period": "2026-02",
        "candidate_dimensions": ["country", "device", "customer_type"],
        "hypothesis_planning_enabled": True,
        **case.get("request_overrides", {}),
    }


def run_benchmark(cases_path: Path | None = None) -> dict[str, object]:
    cases_path = cases_path or Path(__file__).resolve().parents[2] / "evals" / "hypothesis_planning_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        for case in cases:
            outputs = list(case.get("planner_outputs", []))
            def generator(_, output_type):
                if case.get("provider_failure"):
                    raise RuntimeError("fixture provider failure")
                if not outputs:
                    raise RuntimeError("fixture planner output exhausted")
                return output_type.model_validate({"proposals": outputs.pop(0)})
            csv_path = Path(directory) / f"{case['id']}.csv"
            pd.DataFrame(_recursive_rows() if case.get("dataset") == "recursive" else _simple_rows()).to_csv(csv_path, index=False)
            with patch("app.services.hypothesis_planner.generate_structured", generator):
                actual = RootCauseAgent().execute({"cleaned_path": str(csv_path), "investigation_request": _request(case)})["investigation_state"]
            root_record = next(record for record in actual["hypothesis_planning_records"] if not record["filter_path"])
            true_dimension = case["true_driver_dimension"]
            rank = next((item["priority"] for item in root_record["validated_proposals"] if item["target_dimension"] == true_dimension), None)
            invalid_count = len(root_record["rejected_proposals"])
            supplied_count = len(case.get("planner_outputs", [[]])[0]) if case.get("planner_outputs") else 0
            expected = case["expected"]
            mismatches = {key: {"expected": value, "actual": actual.get(key)} for key, value in expected.items() if actual.get(key) != value}
            if case.get("expected_root_scope"):
                actual_scopes = [record["filter_path"] for record in actual["hypothesis_planning_records"]]
                if case["expected_root_scope"] not in actual_scopes:
                    mismatches["planning_scope"] = {"expected": case["expected_root_scope"], "actual": actual_scopes}
            results.append({"id": case["id"], "passed": not mismatches, "mismatches": mismatches, "true_driver_rank": rank, "top_1_hit": rank == 1, "top_3_hit": rank is not None and rank <= 3, "invalid_proposal_count": invalid_count, "supplied_proposal_count": supplied_count, "fallback_occurred": root_record["fallback_reason"] is not None})
    ranks = [item["true_driver_rank"] for item in results if item["true_driver_rank"] is not None]
    supplied = sum(item["supplied_proposal_count"] for item in results)
    return {"total": len(results), "passed": sum(item["passed"] for item in results), "failed": sum(not item["passed"] for item in results), "planner_metrics": {"top_1_hit_rate": sum(item["top_1_hit"] for item in results) / len(results), "top_3_hit_rate": sum(item["top_3_hit"] for item in results) / len(results), "mean_true_driver_rank": sum(ranks) / len(ranks) if ranks else None, "invalid_proposal_rate": sum(item["invalid_proposal_count"] for item in results) / supplied if supplied else 0.0, "fallback_rate": sum(item["fallback_occurred"] for item in results) / len(results)}, "release_ready": all(item["passed"] for item in results), "results": results}


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2))
