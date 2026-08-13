"""Controlled, answer-keyed evaluation for Root Cause Analytics outputs.

This module deliberately does not call or modify the production RootCauseAgent.
It scores exported structured predictions against synthetic incidents with known
answers so analytical capability can be measured independently of runtime and
UI reliability.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


EVALS_DIR = Path(__file__).parents[2] / "evals"
CASES_PATH = EVALS_DIR / "root_cause_cases.json"
REFERENCE_PREDICTIONS_PATH = EVALS_DIR / "root_cause_reference_predictions.json"
BASELINE_PATH = EVALS_DIR / "root_cause_baseline.json"
DEFAULT_REPORT_DIR = EVALS_DIR / "reports" / "root-cause"

CASE_WEIGHTS = {"critical": 5.0, "high": 3.0, "medium": 2.0, "low": 1.0}
METRIC_WEIGHTS = {
    "anomaly_detection": 1.0,
    "incident_classification": 2.0,
    "primary_branch": 2.0,
    "affected_segment": 1.5,
    "contribution_accuracy": 2.0,
    "hypothesis_status_accuracy": 1.5,
    "correct_abstention": 2.0,
    "explained_impact_reconciliation": 2.0,
    "causal_claim_safety": 2.0,
    "evidence_traceability": 2.0,
}
HYPOTHESIS_STATUSES = {"supported", "partially_supported", "rejected", "unresolved"}
INCIDENT_TYPES = {"business_incident", "data_incident", "normal_variation", "insufficient_evidence"}
UNSUPPORTED_CAUSAL_LANGUAGE = re.compile(
    r"(?<!root )(?<!root-)\bcause\b|\b(caused|causes|causing|due to|led to|resulted in|responsible for|root cause (?:is|was))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MetricResult:
    metric: str
    applicable: bool
    score: float
    passed: bool
    detail: str


@dataclass(frozen=True)
class RootCauseCaseResult:
    case_id: str
    name: str
    severity: str
    passed: bool
    metrics: list[MetricResult]
    error: str | None = None


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def load_cases(path: Path = CASES_PATH) -> tuple[str, list[dict[str, Any]]]:
    payload = _read_json(path)
    version = str(payload.get("suite_version") or "").strip()
    cases = payload.get("cases")
    if not version or not isinstance(cases, list) or not cases:
        raise ValueError("RCA case file requires suite_version and a non-empty cases list")
    ids = [str(case.get("id") or "") for case in cases]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("RCA case IDs must be non-empty and unique")
    for case in cases:
        _validate_case(case)
    return version, cases


def load_predictions(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("Prediction file requires a predictions list")
    ids = [str(item.get("case_id") or "") for item in predictions]
    if any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("Prediction case_id values must be non-empty and unique")
    return predictions


def _validate_case(case: dict[str, Any]) -> None:
    expected = case.get("expected")
    if not isinstance(expected, dict):
        raise ValueError(f"Case {case.get('id')} requires an expected answer")
    incident_type = expected.get("incident_type")
    if incident_type not in INCIDENT_TYPES:
        raise ValueError(f"Case {case.get('id')} has unsupported incident_type {incident_type!r}")
    hypotheses = expected.get("hypotheses") or {}
    invalid_statuses = sorted(set(hypotheses.values()) - HYPOTHESIS_STATUSES)
    if invalid_statuses:
        raise ValueError(f"Case {case.get('id')} has unsupported hypothesis statuses: {invalid_statuses}")
    if not isinstance(case.get("available_evidence_ids"), list) or not case["available_evidence_ids"]:
        raise ValueError(f"Case {case.get('id')} requires available_evidence_ids")
    required = set(expected.get("required_evidence_ids") or [])
    if not required.issubset(set(case["available_evidence_ids"])):
        raise ValueError(f"Case {case.get('id')} requires evidence not present in available_evidence_ids")


def _norm(value: object) -> str:
    return re.sub(r"\s+", "_", str(value or "").strip().lower())


def _segment_key(segment: object) -> str:
    if not isinstance(segment, dict):
        return _norm(segment)
    return "|".join(f"{_norm(key)}={_norm(value)}" for key, value in sorted(segment.items()))


def _set_score(expected: Iterable[object], actual: Iterable[object], normalizer=_norm) -> tuple[float, str]:
    expected_set = {normalizer(item) for item in expected}
    actual_set = {normalizer(item) for item in actual}
    union = expected_set | actual_set
    score = 1.0 if not union else len(expected_set & actual_set) / len(union)
    return score, f"expected={sorted(expected_set)!r}; actual={sorted(actual_set)!r}"


def _metric(metric: str, score: float, detail: str, *, applicable: bool = True) -> MetricResult:
    bounded = max(0.0, min(1.0, float(score))) if applicable else 1.0
    return MetricResult(metric, applicable, bounded, (not applicable) or math.isclose(bounded, 1.0), detail)


def _exact_metric(metric: str, expected: object, actual: object) -> MetricResult:
    score = 1.0 if expected == actual else 0.0
    return _metric(metric, score, f"expected={expected!r}; actual={actual!r}")


def _mapping_accuracy(expected: dict[str, object], actual_items: object, *, value_key: str) -> tuple[float, str]:
    actual: dict[str, object] = {}
    if isinstance(actual_items, list):
        for item in actual_items:
            if isinstance(item, dict) and item.get("driver_id"):
                actual[_norm(item["driver_id"])] = item.get(value_key)
    expected_norm = {_norm(key): value for key, value in expected.items()}
    keys = set(expected_norm) | set(actual)
    if not keys:
        return 1.0, "no keyed values expected or returned"
    correct = sum(expected_norm.get(key) == actual.get(key) for key in keys)
    return correct / len(keys), f"expected={expected_norm!r}; actual={actual!r}"


def _contribution_metric(expected: dict[str, Any], prediction: dict[str, Any]) -> MetricResult:
    expected_values = expected.get("contributions")
    if expected_values is None:
        return _metric("contribution_accuracy", 1.0, "not applicable", applicable=False)
    tolerance = float(expected.get("contribution_tolerance", 1e-6))
    actual: dict[str, float] = {}
    for item in prediction.get("contributions") or []:
        try:
            actual[_norm(item["driver_id"])] = float(item["absolute_impact"])
        except (KeyError, TypeError, ValueError):
            continue
    expected_norm = {_norm(key): float(value) for key, value in expected_values.items()}
    keys = set(expected_norm) | set(actual)
    correct = sum(
        key in expected_norm and key in actual and abs(expected_norm[key] - actual[key]) <= tolerance
        for key in keys
    )
    score = correct / len(keys) if keys else 1.0
    return _metric(
        "contribution_accuracy",
        score,
        f"tolerance={tolerance}; expected={expected_norm!r}; actual={actual!r}",
    )


def _reconciliation_metric(expected: dict[str, Any], prediction: dict[str, Any]) -> MetricResult:
    target = expected.get("reconciliation")
    if target is None:
        return _metric("explained_impact_reconciliation", 1.0, "not applicable", applicable=False)
    actual = prediction.get("reconciliation")
    if not isinstance(actual, dict):
        return _metric("explained_impact_reconciliation", 0.0, "prediction omitted reconciliation")
    tolerance = float(target.get("tolerance", 1e-6))
    fields = ("total_movement", "explained_movement", "unexplained_movement")
    checks: list[bool] = []
    for field in fields:
        try:
            checks.append(abs(float(actual[field]) - float(target[field])) <= tolerance)
        except (KeyError, TypeError, ValueError):
            checks.append(False)
    try:
        identity_ok = abs(
            float(actual["total_movement"])
            - (float(actual["explained_movement"]) + float(actual["unexplained_movement"]))
        ) <= tolerance
    except (KeyError, TypeError, ValueError):
        identity_ok = False
    checks.append(identity_ok)
    return _metric(
        "explained_impact_reconciliation",
        sum(checks) / len(checks),
        f"expected={target!r}; actual={actual!r}; identity_ok={identity_ok}",
    )


def _hypothesis_metric(expected: dict[str, Any], prediction: dict[str, Any]) -> MetricResult:
    target = expected.get("hypotheses")
    if target is None:
        return _metric("hypothesis_status_accuracy", 1.0, "not applicable", applicable=False)
    actual_items = [
        {"driver_id": item.get("hypothesis_id"), "status": _norm(item.get("status"))}
        for item in prediction.get("hypotheses") or []
        if isinstance(item, dict)
    ]
    expected_norm = {_norm(key): _norm(value) for key, value in target.items()}
    score, detail = _mapping_accuracy(expected_norm, actual_items, value_key="status")
    return _metric("hypothesis_status_accuracy", score, detail)


def _collect_citations(items: object) -> tuple[list[str], bool]:
    citations: list[str] = []
    every_item_cited = True
    for item in items or []:
        if not isinstance(item, dict):
            every_item_cited = False
            continue
        item_citations = [str(value) for value in item.get("evidence_ids") or [] if str(value).strip()]
        if not item_citations:
            every_item_cited = False
        citations.extend(item_citations)
    return citations, every_item_cited


def _traceability_metric(case: dict[str, Any], prediction: dict[str, Any]) -> MetricResult:
    available = {str(item) for item in case["available_evidence_ids"]}
    required = {str(item) for item in case["expected"].get("required_evidence_ids") or []}
    evidence = prediction.get("evidence") or []
    declared = [str(item.get("evidence_id")) for item in evidence if isinstance(item, dict) and item.get("evidence_id")]
    declared_set = set(declared)
    citations: list[str] = []
    citation_checks: list[bool] = []
    for key in ("findings", "contributions", "hypotheses"):
        values = prediction.get(key) or []
        if values:
            found, complete = _collect_citations(values)
            citations.extend(found)
            citation_checks.append(complete)
    cited = set(citations)
    checks = [
        bool(declared),
        len(declared) == len(declared_set),
        declared_set.issubset(available),
        cited.issubset(declared_set),
        required.issubset(cited),
        all(citation_checks) if citation_checks else False,
    ]
    return _metric(
        "evidence_traceability",
        sum(checks) / len(checks),
        (
            f"declared={sorted(declared_set)!r}; cited={sorted(cited)!r}; "
            f"required={sorted(required)!r}; available={sorted(available)!r}"
        ),
    )


def _causal_safety_metric(expected: dict[str, Any], prediction: dict[str, Any]) -> MetricResult:
    if bool(expected.get("causal_evidence")):
        return _metric("causal_claim_safety", 1.0, "case permits causal wording because causal evidence is declared")
    text_parts = [str(prediction.get("conclusion") or "")]
    for key in ("findings", "hypotheses"):
        text_parts.extend(str(item.get("statement") or "") for item in prediction.get(key) or [] if isinstance(item, dict))
    matches = sorted({match.group(0).lower() for match in UNSUPPORTED_CAUSAL_LANGUAGE.finditer(" ".join(text_parts))})
    return _metric(
        "causal_claim_safety",
        0.0 if matches else 1.0,
        f"unsupported causal phrases={matches!r}" if matches else "no unsupported causal wording detected",
    )


def score_case(case: dict[str, Any], prediction: dict[str, Any] | None) -> RootCauseCaseResult:
    if prediction is None:
        metrics = [
            _metric(name, 0.0, "prediction missing")
            for name in METRIC_WEIGHTS
        ]
        return RootCauseCaseResult(case["id"], case["name"], case["severity"], False, metrics, "prediction missing")

    expected = case["expected"]
    branch_score, branch_detail = _set_score(expected.get("primary_branches") or [], prediction.get("primary_branches") or [])
    segment_score, segment_detail = _set_score(
        expected.get("affected_segments") or [], prediction.get("affected_segments") or [], normalizer=_segment_key
    )
    metrics = [
        _metric(
            "anomaly_detection",
            1.0,
            "not applicable",
            applicable=expected.get("is_anomaly") is not None,
        )
        if expected.get("is_anomaly") is None
        else _exact_metric("anomaly_detection", expected["is_anomaly"], prediction.get("is_anomaly")),
        _exact_metric("incident_classification", expected["incident_type"], prediction.get("incident_type")),
        _metric("primary_branch", branch_score, branch_detail),
        _metric("affected_segment", segment_score, segment_detail),
        _contribution_metric(expected, prediction),
        _hypothesis_metric(expected, prediction),
        _exact_metric("correct_abstention", bool(expected.get("must_abstain")), bool(prediction.get("abstained"))),
        _reconciliation_metric(expected, prediction),
        _causal_safety_metric(expected, prediction),
        _traceability_metric(case, prediction),
    ]
    return RootCauseCaseResult(
        case["id"],
        case["name"],
        case["severity"],
        all(metric.passed for metric in metrics if metric.applicable),
        metrics,
    )


def summarize(
    results: list[RootCauseCaseResult],
    suite_version: str,
    baseline_path: Path = BASELINE_PATH,
) -> dict[str, Any]:
    baseline = _read_json(baseline_path) if baseline_path.exists() else {}
    metric_scores: dict[str, float] = {}
    metric_counts: dict[str, int] = {}
    for metric_name in METRIC_WEIGHTS:
        pairs = [
            (metric, CASE_WEIGHTS[result.severity])
            for result in results
            for metric in result.metrics
            if metric.metric == metric_name and metric.applicable
        ]
        denominator = sum(weight for _, weight in pairs)
        metric_scores[metric_name] = round(
            sum(metric.score * weight for metric, weight in pairs) / denominator if denominator else 1.0,
            6,
        )
        metric_counts[metric_name] = len(pairs)

    denominator = sum(METRIC_WEIGHTS.values())
    overall_score = sum(metric_scores[name] * weight for name, weight in METRIC_WEIGHTS.items()) / denominator
    minimum_metric_scores = {
        name: float(value) for name, value in (baseline.get("minimum_metric_scores") or {}).items()
    }
    below_threshold = sorted(
        name for name, minimum in minimum_metric_scores.items() if metric_scores.get(name, 0.0) < minimum
    )
    critical_failures = sorted(result.case_id for result in results if result.severity == "critical" and not result.passed)
    minimum_overall = float(baseline.get("minimum_overall_score", 1.0))
    release_ready = not critical_failures and not below_threshold and overall_score >= minimum_overall
    return {
        "suite_version": suite_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "passed_count": sum(result.passed for result in results),
        "failed_count": sum(not result.passed for result in results),
        "overall_score": round(overall_score, 6),
        "metric_scores": metric_scores,
        "metric_case_counts": metric_counts,
        "critical_failures": critical_failures,
        "metrics_below_threshold": below_threshold,
        "release_ready": release_ready,
        "thresholds": {
            "minimum_overall_score": minimum_overall,
            "minimum_metric_scores": minimum_metric_scores,
        },
    }


def combine_with_analytical_release(
    analytical_summary: dict[str, Any], root_cause_summary: dict[str, Any]
) -> dict[str, Any]:
    """Add the independent RCA gate without changing legacy category scores.

    The existing deterministic evaluator has callers that assert its exact
    category set. This explicit integration hook therefore preserves those
    fields and nests RCA metrics under ``root_cause_gate``.
    """

    combined = dict(analytical_summary)
    combined.update(
        {
            "analytical_release_ready": bool(analytical_summary.get("release_ready")),
            "root_cause_release_ready": bool(root_cause_summary.get("release_ready")),
            "release_ready": bool(analytical_summary.get("release_ready"))
            and bool(root_cause_summary.get("release_ready")),
            "case_count": int(analytical_summary.get("case_count", 0))
            + int(root_cause_summary.get("case_count", 0)),
            "passed_count": int(analytical_summary.get("passed_count", 0))
            + int(root_cause_summary.get("passed_count", 0)),
            "failed_count": int(analytical_summary.get("failed_count", 0))
            + int(root_cause_summary.get("failed_count", 0)),
            "root_cause_gate": root_cause_summary,
        }
    )
    return combined


def evaluate(
    cases_path: Path = CASES_PATH,
    predictions_path: Path = REFERENCE_PREDICTIONS_PATH,
    baseline_path: Path = BASELINE_PATH,
) -> tuple[dict[str, Any], list[RootCauseCaseResult]]:
    suite_version, cases = load_cases(cases_path)
    predictions = load_predictions(predictions_path)
    known_ids = {case["id"] for case in cases}
    unknown = sorted({item["case_id"] for item in predictions} - known_ids)
    if unknown:
        raise ValueError(f"Predictions contain unknown RCA case IDs: {unknown}")
    by_id = {item["case_id"]: item for item in predictions}
    results = [score_case(case, by_id.get(case["id"])) for case in cases]
    return summarize(results, suite_version, baseline_path), results


def write_reports(
    summary: dict[str, Any],
    results: list[RootCauseCaseResult],
    destination: Path = DEFAULT_REPORT_DIR,
) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "latest.json"
    html_path = destination / "latest.html"
    json_path.write_text(
        json.dumps({"summary": summary, "cases": [asdict(result) for result in results]}, indent=2),
        encoding="utf-8",
    )
    metric_rows = "".join(
        f"<tr><td>{html.escape(name.replace('_', ' ').title())}</td><td>{score:.1%}</td></tr>"
        for name, score in summary["metric_scores"].items()
    )
    case_rows = "".join(
        f"<tr><td>{html.escape(result.case_id)}</td><td>{html.escape(result.name)}</td>"
        f"<td>{html.escape(result.severity)}</td><td>{'PASS' if result.passed else 'FAIL'}</td></tr>"
        for result in results
    )
    status_class = "ok" if summary["release_ready"] else "bad"
    html_path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Root Cause Evaluation</title>"
        "<style>body{font:15px system-ui;margin:40px;color:#17213a;max-width:1100px}"
        "h1{margin-bottom:4px}.score{font-size:36px;font-weight:800}.ok{color:#087f5b}.bad{color:#b42318}"
        "table{border-collapse:collapse;width:100%;margin:20px 0}th,td{padding:10px;border-bottom:1px solid #dce3ec;text-align:left}"
        "th{background:#f5f7fa}</style>"
        f"<h1>Controlled Root Cause Evaluation</h1><p>Suite {html.escape(summary['suite_version'])}</p>"
        f"<div class='score {status_class}'>{summary['overall_score']:.1%}</div>"
        f"<p>Release gate: <b>{'READY' if summary['release_ready'] else 'BLOCKED'}</b> &middot; "
        f"{summary['passed_count']}/{summary['case_count']} incidents passed</p>"
        f"<h2>Scorecard</h2><table><tr><th>Metric</th><th>Score</th></tr>{metric_rows}</table>"
        f"<h2>Incident results</h2><table><tr><th>ID</th><th>Incident</th><th>Severity</th><th>Status</th></tr>{case_rows}</table>",
        encoding="utf-8",
    )
    return json_path, html_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Score structured Root Cause Analytics predictions")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    summary, results = evaluate(args.cases, args.predictions, args.baseline)
    for result in results:
        print(f"[{'PASS' if result.passed else 'FAIL'}] [{result.severity.upper()}] {result.case_id}: {result.name}")
        for metric in result.metrics:
            if metric.applicable and not metric.passed:
                print(f"  - {metric.metric}: {metric.score:.1%} ({metric.detail})")
    print(
        f"\nRCA score: {summary['overall_score']:.1%} | "
        f"{summary['passed_count']}/{summary['case_count']} passed | "
        f"Release: {'READY' if summary['release_ready'] else 'BLOCKED'}"
    )
    if not args.no_report:
        json_path, html_path = write_reports(summary, results, args.report_dir)
        print(f"Reports: {json_path} | {html_path}")
    return 0 if summary["release_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
