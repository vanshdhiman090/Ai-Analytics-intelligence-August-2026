"""Production-path robustness benchmark for the public V1 RCA service.

The runner never duplicates RCA calculations. It independently checks fixture
totals, calls the real public service mapping, and compares structured output
with explicit answer keys.
"""

from __future__ import annotations

import argparse
import json
import math
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pandas as pd

from app.api.rca_contracts import RCAInvestigationRequestV1
from app.services.rca_api import execute_rca_request


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "real_world_rca_benchmark_cases.json"
_FIXED_DATASET_ID = UUID("00000000-0000-4000-8000-000000000003")
_ABS_TOLERANCE = 1e-7


def _provider_failure(*_args: object, **_kwargs: object) -> object:
    raise RuntimeError("Phase 3C deterministic benchmark provider fallback")


def _fallback_safe_execution() -> ExitStack:
    stack = ExitStack()
    stack.enter_context(patch("app.services.hypothesis_planner.generate_structured", _provider_failure))
    stack.enter_context(patch("app.services.investigation_controller.generate_structured", _provider_failure))
    stack.enter_context(patch("app.services.investigation_verifier.generate_structured", _provider_failure))
    return stack


def _number_matches(actual: object, expected: object) -> bool:
    if expected is None:
        return actual is None
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), float(expected), rel_tol=1e-9, abs_tol=_ABS_TOLERANCE
        )
    return actual == expected


def _compare(actual: object, expected: object, path: str = "") -> list[dict[str, object]]:
    mismatches: list[dict[str, object]] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"field": path or "<root>", "expected": expected, "actual": actual}]
        for key, value in expected.items():
            mismatches.extend(_compare(actual.get(key), value, f"{path}.{key}".strip(".")))
        return mismatches
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [{"field": path, "expected": expected, "actual": actual}]
        for index, value in enumerate(expected):
            mismatches.extend(_compare(actual[index], value, f"{path}[{index}]"))
        return mismatches
    if not _number_matches(actual, expected):
        mismatches.append({"field": path, "expected": expected, "actual": actual})
    return mismatches


def _ground_truth(frame: pd.DataFrame, case: dict[str, Any]) -> dict[str, object]:
    request = case["request"]
    metric = request["kpi"]["metric_column"]
    time_column = request["kpi"]["time_column"]
    periods = pd.to_datetime(frame[time_column], errors="raise").dt.to_period(
        request["kpi"]["time_grain"][0].upper()
    ).astype(str)
    values = pd.to_numeric(frame[metric], errors="raise")
    totals = values.groupby(periods).sum()
    baseline = float(totals.get(request["baseline_period"], 0.0))
    comparison = float(totals.get(request["comparison_period"], 0.0))
    record_id = case["record_id_column"]
    return {
        "row_count": len(frame),
        "baseline_value": baseline,
        "comparison_value": comparison,
        "signed_change": comparison - baseline,
        "duplicate_record_ids": int(frame[record_id].duplicated().sum()),
        "required_null_cells": int(
            frame[
                [
                    time_column,
                    record_id,
                    metric,
                    *request["candidate_dimensions"],
                ]
            ].isna().sum().sum()
        ),
    }


def _public_projection(response: object) -> dict[str, object]:
    path = [
        {
            "dimension": step.dimension,
            "segment": step.segment,
            "signed_change": step.segment_movement,
            "local_contribution_pct": step.local_contribution_pct,
        }
        for step in response.investigation_path
    ]
    issues = list(response.data_quality.issues)
    decomposition = response.selected_decomposition
    return {
        "public_kpi": {
            "baseline_value": response.kpi_movement.baseline_value,
            "comparison_value": response.kpi_movement.comparison_value,
            "signed_change": response.kpi_movement.signed_change,
        },
        "path": path,
        "claim": response.conclusion.claim,
        "terminal_status": response.conclusion.terminal_status,
        "readiness": response.conclusion.readiness.model_dump(mode="json"),
        "robustness": response.conclusion.robustness.model_dump(mode="json"),
        "data_quality": {
            "status": response.data_quality.status,
            "issue_codes": sorted(item.code for item in issues),
            "selected_target_issue": any(item.affects_selected_target for item in issues),
        },
        "decomposition": (
            {
                "reconciles": decomposition.reconciles,
                "reconciliation_residual": decomposition.reconciliation_residual,
                "parent_movement": decomposition.parent_movement,
                "leading_segment_movement": decomposition.leading_segment_movement,
                "remaining_segment_movement": decomposition.remaining_segment_movement,
                "positive_offsets": decomposition.positive_offsets,
            }
            if decomposition is not None
            else None
        ),
    }


def _invariance_projection(response: object) -> dict[str, object]:
    projection = _public_projection(response)
    return {
        "public_kpi": projection["public_kpi"],
        "path": projection["path"],
        "claim": projection["claim"],
        "terminal_status": projection["terminal_status"],
        "readiness": projection["readiness"],
        "robustness": projection["robustness"],
        "data_quality": projection["data_quality"],
        "decomposition": projection["decomposition"],
    }


def _request(case: dict[str, Any]) -> RCAInvestigationRequestV1:
    return RCAInvestigationRequestV1(
        dataset_id=_FIXED_DATASET_ID,
        **case["request"],
    )


def run_case(case: dict[str, Any], repository_root: Path = REPOSITORY_ROOT) -> dict[str, object]:
    dataset_path = repository_root / case["dataset_path"]
    frame = pd.read_csv(dataset_path)
    independent = _ground_truth(frame, case)
    ground_truth_mismatches = _compare(independent, case["ground_truth"], "ground_truth")
    if independent["duplicate_record_ids"]:
        ground_truth_mismatches.append(
            {"field": "ground_truth.duplicate_record_ids", "expected": 0, "actual": independent["duplicate_record_ids"]}
        )
    if independent["required_null_cells"]:
        ground_truth_mismatches.append(
            {"field": "ground_truth.required_null_cells", "expected": 0, "actual": independent["required_null_cells"]}
        )

    with _fallback_safe_execution():
        response = execute_rca_request(frame, _request(case))
        actual = _public_projection(response)
        engine_mismatches = _compare(actual, case["expected"], "engine_output")
        shuffle_invariant: bool | None = None
        if case.get("shuffle"):
            shuffled = frame.sample(frac=1.0, random_state=3103).reset_index(drop=True)
            shuffled_response = execute_rca_request(shuffled, _request(case))
            shuffle_invariant = _invariance_projection(response) == _invariance_projection(
                shuffled_response
            )
            if not shuffle_invariant:
                engine_mismatches.append(
                    {
                        "field": "engine_output.row_shuffle_invariance",
                        "expected": True,
                        "actual": False,
                    }
                )

    passed = not ground_truth_mismatches and not engine_mismatches
    return {
        "id": case["id"],
        "scenario": case["scenario"],
        "passed": passed,
        "provider_mode": "deterministic_fallback",
        "ground_truth_expectation": case["ground_truth"],
        "independent_ground_truth": independent,
        "engine_output": actual,
        "expected_engine_output": case["expected"],
        "row_shuffle_invariant": shuffle_invariant,
        "mismatches": [*ground_truth_mismatches, *engine_mismatches],
    }


def run_benchmark(
    cases_path: Path = DEFAULT_CASES_PATH,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, object]:
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    results = [run_case(case, repository_root) for case in payload["cases"]]
    passed = sum(bool(item["passed"]) for item in results)
    return {
        "suite_version": payload["suite_version"],
        "provider_mode": "deterministic_fallback",
        "case_count": len(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "release_ready": passed == len(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production-path real-world RCA benchmarks")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    args = parser.parse_args()
    summary = run_benchmark(args.cases)
    for result in summary["results"]:
        print(f"[{'PASS' if result['passed'] else 'FAIL'}] {result['id']}: {result['scenario']}")
        print("  GROUND-TRUTH EXPECTATION:", json.dumps(result["ground_truth_expectation"], sort_keys=True))
        print("  ENGINE OUTPUT:", json.dumps(result["engine_output"], sort_keys=True))
        for mismatch in result["mismatches"]:
            print("  MISMATCH:", json.dumps(mismatch, sort_keys=True))
    print(
        f"\nPhase 3C: {summary['passed_count']}/{summary['case_count']} passed | "
        f"Release: {'READY' if summary['release_ready'] else 'BLOCKED'} | "
        f"Provider: {summary['provider_mode']}"
    )
    return 0 if summary["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
