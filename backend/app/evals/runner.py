"""Versioned, deterministic release evaluation for the controlled analytics engine."""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.domain.contracts import AnalysisPlan
from app.services.analysis import AnalysisPlanError, execute_plan, validate_question_coverage

EVALS_DIR = Path(__file__).parents[2] / "evals"
CASES_PATH = EVALS_DIR / "golden_cases.json"
BASELINE_PATH = EVALS_DIR / "baseline.json"
DEFAULT_REPORT_DIR = EVALS_DIR / "reports"
WEIGHTS = {"critical": 5, "high": 3, "medium": 2, "low": 1}


@dataclass(frozen=True)
class AssertionResult:
    passed: bool
    assertion: str
    detail: str


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    name: str
    category: str
    severity: str
    passed: bool
    assertions: list[AssertionResult]
    error: str | None = None


def _load_cases(path: Path) -> tuple[str, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return "legacy", payload
    return str(payload["suite_version"]), list(payload["cases"])


def _resolve(value: Any, path: str) -> Any:
    tokens = path.split(".") if path else []

    def walk(current: Any, remaining: list[str]) -> Any:
        if not remaining:
            return current
        token, *tail = remaining
        if token == "*":
            return [walk(item, tail) for item in current]
        next_value = current[int(token)] if isinstance(current, list) else current[token]
        return walk(next_value, tail)

    return walk(value, tokens)


def _flatten(values: Any) -> list[Any]:
    if not isinstance(values, list):
        return [values]
    flattened: list[Any] = []
    for value in values:
        flattened.extend(_flatten(value))
    return flattened


def _assert(payload: dict, spec: dict) -> AssertionResult:
    kind = spec["type"]
    path = spec.get("path", "")
    try:
        actual = _resolve(payload, path)
        expected = spec.get("expected")
        tolerance = float(spec.get("tolerance", 1e-9))
        if kind == "equals":
            passed = actual == expected
        elif kind == "approx":
            passed = abs(float(actual) - float(expected)) <= tolerance
        elif kind == "contains":
            passed = str(expected).lower() in str(actual).lower()
        elif kind == "between":
            passed = float(spec["minimum"]) <= float(actual) <= float(spec["maximum"])
        elif kind == "length":
            passed = len(actual) == int(expected)
        elif kind == "sum_approx":
            passed = abs(sum(float(item) for item in _flatten(actual)) - float(expected)) <= tolerance
        elif kind == "unique":
            values = _flatten(actual)
            passed = len(values) == len(set(values))
        elif kind == "is_null":
            passed = actual is None
        elif kind == "not_null":
            passed = actual is not None
        else:
            raise ValueError(f"Unsupported assertion type: {kind}")
        detail = f"{path or 'payload'}: expected {kind} {expected!r}, got {actual!r}"
        return AssertionResult(passed, kind, detail)
    except Exception as exc:
        return AssertionResult(False, kind, f"{path or 'payload'} could not be evaluated: {exc}")


def _legacy_case(case: dict) -> dict:
    expectation = case.get("expectation", {})
    assertion: dict[str, Any]
    if "equals" in expectation:
        assertion = {
            "type": "equals",
            "path": f"results.{expectation.get('result_index', 0)}.rows.{expectation.get('row_index', 0)}.{expectation['field']}",
            "expected": expectation["equals"],
        }
    else:
        assertion = {
            "type": "contains",
            "path": f"results.{expectation.get('result_index', 0)}.caveats",
            "expected": expectation.get("caveat_contains", ""),
        }
    return {
        **case,
        "id": case.get("id", case["name"].lower().replace(" ", "-")),
        "category": case.get("category", "legacy"),
        "severity": case.get("severity", "medium"),
        "assertions": [assertion],
    }


def run_case(case: dict) -> CaseResult:
    case = _legacy_case(case) if "assertions" not in case else case
    frame = pd.DataFrame(case["rows"])
    plan = AnalysisPlan.model_validate(case["plan"])
    expected_error = case.get("expected_error")
    try:
        if case.get("question"):
            validate_question_coverage(frame, plan, case["question"])
        first = execute_plan(frame, plan)
        second = execute_plan(frame, plan) if case.get("deterministic", True) else first
        payload = {"results": [item.model_dump(mode="json") for item in first]}
        if expected_error:
            assertions = [AssertionResult(False, "expected_error", f"Expected error containing {expected_error!r}, but execution succeeded")]
        else:
            assertions = [_assert(payload, spec) for spec in case.get("assertions", [])]
            if case.get("deterministic", True):
                same = [item.model_dump(mode="json") for item in first] == [item.model_dump(mode="json") for item in second]
                assertions.append(AssertionResult(same, "deterministic", "Repeated execution produced identical evidence" if same else "Repeated execution changed evidence"))
        return CaseResult(case["id"], case["name"], case["category"], case["severity"], all(item.passed for item in assertions), assertions)
    except (AnalysisPlanError, ValueError) as exc:
        matched = bool(expected_error and expected_error.lower() in str(exc).lower())
        assertion = AssertionResult(matched, "expected_error", f"Expected {expected_error!r}; got {str(exc)!r}")
        return CaseResult(case["id"], case["name"], case["category"], case["severity"], matched, [assertion], str(exc))


def summarize(results: list[CaseResult], suite_version: str, baseline_path: Path = BASELINE_PATH) -> dict:
    total_weight = sum(WEIGHTS[item.severity] for item in results)
    passed_weight = sum(WEIGHTS[item.severity] for item in results if item.passed)
    score = passed_weight / total_weight if total_weight else 0.0
    category_scores = {}
    for category in sorted({item.category for item in results}):
        subset = [item for item in results if item.category == category]
        category_scores[category] = sum(item.passed for item in subset) / len(subset)
    critical_failures = [item.case_id for item in results if item.severity == "critical" and not item.passed]
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {"minimum_weighted_score": 1.0, "minimum_category_score": 1.0}
    minimum_score = float(baseline.get("minimum_weighted_score", 1.0))
    minimum_category = float(baseline.get("minimum_category_score", 1.0))
    release_ready = not critical_failures and score >= minimum_score and all(value >= minimum_category for value in category_scores.values())
    return {
        "suite_version": suite_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "passed_count": sum(item.passed for item in results),
        "failed_count": sum(not item.passed for item in results),
        "weighted_score": round(score, 6),
        "category_scores": category_scores,
        "critical_failures": critical_failures,
        "release_ready": release_ready,
        "thresholds": {"minimum_weighted_score": minimum_score, "minimum_category_score": minimum_category},
    }


def run_suite(path: Path = CASES_PATH) -> list[dict]:
    _, cases = _load_cases(path)
    return [asdict(run_case(case)) for case in cases]


def evaluate(path: Path = CASES_PATH) -> tuple[dict, list[CaseResult]]:
    version, cases = _load_cases(path)
    results = [run_case(case) for case in cases]
    return summarize(results, version), results


def write_reports(summary: dict, results: list[CaseResult], destination: Path = DEFAULT_REPORT_DIR) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "cases": [asdict(item) for item in results]}
    json_path = destination / "latest.json"
    html_path = destination / "latest.html"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(
        f"<tr class='{'pass' if item.passed else 'fail'}'><td>{html.escape(item.case_id)}</td><td>{html.escape(item.category)}</td><td>{html.escape(item.severity)}</td><td>{'PASS' if item.passed else 'FAIL'}</td><td>{html.escape('; '.join(a.detail for a in item.assertions if not a.passed) or 'All checks passed')}</td></tr>"
        for item in results
    )
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Analytics Accuracy Evaluation</title><style>body{font:15px system-ui;margin:40px;color:#17213a}h1{margin-bottom:4px}.score{font-size:32px;font-weight:800}.ok{color:#087f5b}.bad,.fail{color:#b42318}table{border-collapse:collapse;width:100%;margin-top:24px}th,td{padding:10px;border-bottom:1px solid #dce3ec;text-align:left}th{background:#f5f7fa}.pass td:nth-child(4){color:#087f5b;font-weight:700}.fail td:nth-child(4){font-weight:700}</style>"
        f"<h1>Analytics Accuracy & Regression Evaluation</h1><p>Suite {html.escape(summary['suite_version'])}</p><div class='score {'ok' if summary['release_ready'] else 'bad'}'>{summary['weighted_score']:.1%}</div><p>Release gate: <b>{'READY' if summary['release_ready'] else 'BLOCKED'}</b> · {summary['passed_count']}/{summary['case_count']} cases passed</p>"
        f"<table><thead><tr><th>Case</th><th>Layer</th><th>Severity</th><th>Status</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table>",
        encoding="utf-8",
    )
    return json_path, html_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic analytics release evaluation")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    summary, results = evaluate(args.cases)
    for item in results:
        print(f"[{'PASS' if item.passed else 'FAIL'}] [{item.severity.upper()}] {item.case_id}: {item.name}")
        for assertion in item.assertions:
            if not assertion.passed:
                print(f"  - {assertion.detail}")
    print(f"\nWeighted score: {summary['weighted_score']:.1%} | {summary['passed_count']}/{summary['case_count']} passed | Release: {'READY' if summary['release_ready'] else 'BLOCKED'}")
    if not args.no_report:
        json_path, html_path = write_reports(summary, results, args.report_dir)
        print(f"Reports: {json_path} | {html_path}")
    return 0 if summary["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
