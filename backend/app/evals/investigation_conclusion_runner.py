"""Milestone 6 answer-keyed and metamorphic conclusion evaluation."""

from __future__ import annotations

import json
import math
import random
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.agent.subagents.root_cause_agent import RootCauseAgent
from app.evals.investigation_verification_runner import (
    _DATASETS as VERIFICATION_DATASETS,
    _challenge_planner,
    _controller,
    _hypothesis_planner,
)


def _rows_from_changes(cells):
    rows = []
    for country, device, customer_type, change in cells:
        rows.extend(
            [
                {"date": "2026-01-01", "country": country, "device": device, "customer_type": customer_type, "revenue": 200.0},
                {"date": "2026-02-01", "country": country, "device": device, "customer_type": customer_type, "revenue": 200.0 + change},
            ]
        )
    return rows


def _recursive_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Returning", -45),
            ("Germany", "Mobile", "New", -15),
            ("Germany", "Desktop", "Returning", -10),
            ("Germany", "Desktop", "New", -10),
            ("France", "Mobile", "Returning", -2),
            ("France", "Desktop", "New", -3),
            ("UK", "Mobile", "New", -5),
            ("UK", "Desktop", "Returning", -10),
        ]
    )


def _add_group(rows, period, country, device, customer_type, count, total):
    for _ in range(count):
        rows.append(
            {"date": f"{period}-01", "country": country, "device": device, "customer_type": customer_type, "revenue": total / count}
        )


def _downstream_quality_rows():
    rows = []
    for args in (
        ("2026-01", "Germany", "Mobile", "Returning", 6, 120),
        ("2026-01", "Germany", "Mobile", "New", 4, 80),
        ("2026-01", "Germany", "Desktop", "Returning", 3, 60),
        ("2026-01", "Germany", "Desktop", "New", 2, 40),
        ("2026-02", "Germany", "Mobile", "Returning", 3, 60),
        ("2026-02", "Germany", "Mobile", "New", 2, 40),
        ("2026-02", "Germany", "Desktop", "Returning", 6, 54),
        ("2026-02", "Germany", "Desktop", "New", 4, 36),
        ("2026-01", "France", "Mobile", "Returning", 8, 160),
        ("2026-01", "France", "Desktop", "New", 7, 140),
        ("2026-02", "France", "Mobile", "Returning", 8, 155),
        ("2026-02", "France", "Desktop", "New", 7, 135),
    ):
        _add_group(rows, *args)
    return rows


def _diffuse_rows():
    return _rows_from_changes(
        [
            ("Germany", "Mobile", "Returning", -20),
            ("France", "Desktop", "New", -18),
            ("UK", "Tablet", "Guest", -17),
            ("Spain", "Console", "Trial", -16),
            ("Italy", "TV", "Loyal", -15),
            ("Poland", "Other", "Unknown", -14),
        ]
    )


_DATASETS = {
    **VERIFICATION_DATASETS,
    "recursive": _recursive_rows,
    "downstream_quality": _downstream_quality_rows,
    "diffuse": _diffuse_rows,
}


def _request(case):
    controlled = case.get("controlled_mode", True)
    dimensions = (
        ["country", "device", "channel"]
        if case["dataset"] in VERIFICATION_DATASETS
        else ["country", "device", "customer_type"]
    )
    return {
        "investigation_id": case["id"],
        "goal": "Investigate the revenue decline",
        "kpi": {"metric_name": "Revenue", "metric_column": "revenue", "time_column": "date", "aggregation": "sum", "time_grain": "month"},
        "baseline_period": "2026-01",
        "comparison_period": "2026-02",
        "candidate_dimensions": case.get("candidate_dimensions", dimensions),
        "hypothesis_planning_enabled": controlled,
        "evidence_driven_control_enabled": controlled,
        "self_falsification_enabled": controlled,
        "conclusion_compilation_enabled": True,
        "maximum_depth": case.get("maximum_depth", 1),
        "minimum_rows_per_period_for_drill_down": 1,
        "material_contribution_pct": case.get("material_contribution_pct", 20.0),
    }


def _execute(rows, request, provider_mode="none"):
    with tempfile.TemporaryDirectory() as directory:
        csv_path = Path(directory) / "case.csv"
        pd.DataFrame(rows).to_csv(csv_path, index=False)
        if provider_mode == "none":
            result = RootCauseAgent().execute(
                {"cleaned_path": str(csv_path), "investigation_request": request}
            )
        else:
            with (
                patch("app.services.hypothesis_planner.generate_structured", _hypothesis_planner),
                patch("app.services.investigation_controller.generate_structured", _controller),
                patch("app.services.investigation_verifier.generate_structured", _challenge_planner(provider_mode)),
            ):
                result = RootCauseAgent().execute(
                    {"cleaned_path": str(csv_path), "investigation_request": request}
                )
    return result["investigation_state"]


def _projection(conclusion):
    return {
        "claim_type": conclusion["claim_type"],
        "readiness_status": conclusion["readiness_status"],
        "terminal_category": conclusion["terminal_category"],
        "leading_dimension": conclusion["leading_dimension"],
        "leading_segment": conclusion["leading_segment"],
        "contribution_to_net_change_pct": conclusion["contribution_to_net_change_pct"],
        "evidence_strength": conclusion["evidence_strength"],
        "robustness_status": conclusion["robustness_status"],
        "path": [(item["dimension"], item["segment"]) for item in conclusion["target_scope"]["filter_path"]],
        "caveat_codes": sorted(conclusion["caveat_codes"]),
    }


def _case_passed(conclusion, state, expected):
    for key in (
        "claim_type",
        "readiness_status",
        "terminal_category",
        "leading_dimension",
        "leading_segment",
        "robustness_status",
    ):
        if key in expected and conclusion.get(key) != expected[key]:
            return False
    if "required_caveat" in expected and expected["required_caveat"] not in conclusion["caveat_codes"]:
        return False
    if "path_length" in expected and len(conclusion["conclusion_path_node_ids"]) != expected["path_length"]:
        return False
    if "minimum_abs_contribution_pct" in expected and abs(conclusion["contribution_to_net_change_pct"] or 0.0) <= expected["minimum_abs_contribution_pct"]:
        return False
    planning = state.get("challenge_planning_record")
    if "fallback_reason" in expected and (not planning or planning["fallback_reason"] != expected["fallback_reason"]):
        return False
    return True


def run_answer_keyed(cases_path: Path | None = None):
    cases_path = cases_path or Path(__file__).resolve().parents[2] / "evals" / "investigation_conclusion_cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    projections = {}
    for case in cases:
        state = _execute(_DATASETS[case["dataset"]](), _request(case), case["provider_mode"])
        conclusion = state["final_conclusion"]
        passed = _case_passed(conclusion, state, case["expected"])
        results.append({"id": case["id"], "passed": passed, **_projection(conclusion)})
        if case.get("parity_group"):
            projections.setdefault(case["parity_group"], []).append(_projection(conclusion))
    parity = all(len(items) == 2 and items[0] == items[1] for items in projections.values())
    return {
        "case_count": len(results),
        "passed_count": sum(item["passed"] for item in results),
        "all_passed": all(item["passed"] for item in results),
        "provider_fallback_parity": parity,
        "results": results,
    }


def run_metamorphic():
    base_rows = _recursive_rows()
    base_case = {"id": "metamorphic-base", "dataset": "recursive", "provider_mode": "none", "controlled_mode": False, "maximum_depth": 3}
    base_request = _request(base_case)
    base = _execute(base_rows, base_request)["final_conclusion"]
    base_projection = _projection(base)

    shuffled = list(base_rows)
    random.Random(617).shuffle(shuffled)
    row_projection = _projection(_execute(shuffled, {**base_request, "investigation_id": "metamorphic-row"})["final_conclusion"])

    reversed_dimensions = ["customer_type", "device", "country"]
    dimension_projection = _projection(_execute(base_rows, {**base_request, "investigation_id": "metamorphic-dimension", "candidate_dimensions": reversed_dimensions})["final_conclusion"])

    scaled_rows = [{**row, "revenue": row["revenue"] * 7.0} for row in base_rows]
    scaled = _execute(scaled_rows, {**base_request, "investigation_id": "metamorphic-scale"})["final_conclusion"]
    scale_projection = _projection(scaled)
    scale_ok = (
        {k: v for k, v in base_projection.items() if k != "contribution_to_net_change_pct"}
        == {k: v for k, v in scale_projection.items() if k != "contribution_to_net_change_pct"}
        and math.isclose(base_projection["contribution_to_net_change_pct"], scale_projection["contribution_to_net_change_pct"], rel_tol=1e-9, abs_tol=1e-9)
        and math.isclose(scaled["signed_contribution"], base["signed_contribution"] * 7.0, rel_tol=1e-9, abs_tol=1e-9)
    )

    renamed_rows = [{**row, "country": "DE" if row["country"] == "Germany" else row["country"]} for row in base_rows]
    renamed = _projection(_execute(renamed_rows, {**base_request, "investigation_id": "metamorphic-label"})["final_conclusion"])
    renamed["leading_segment"] = "Germany" if renamed["leading_segment"] == "DE" else renamed["leading_segment"]
    renamed["path"] = [(dimension, "Germany" if segment == "DE" else segment) for dimension, segment in renamed["path"]]

    checks = {
        "row_order_invariance": row_projection == base_projection,
        "candidate_dimension_order_invariance": dimension_projection == base_projection,
        "scale_invariance": scale_ok,
        "label_renaming_equivariance": renamed == base_projection,
    }
    return {"all_passed": all(checks.values()), "checks": checks}


def run_benchmark():
    answer_keyed = run_answer_keyed()
    metamorphic = run_metamorphic()
    return {
        "release_ready": answer_keyed["all_passed"] and answer_keyed["provider_fallback_parity"] and metamorphic["all_passed"],
        "answer_keyed": answer_keyed,
        "metamorphic": metamorphic,
    }


def main():
    print(json.dumps(run_benchmark(), indent=2))


if __name__ == "__main__":
    main()

