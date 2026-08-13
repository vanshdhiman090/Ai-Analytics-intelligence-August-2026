from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest
from pydantic import ValidationError

from app.domain.root_cause_contracts import InvestigationConclusion
from app.services.investigation_conclusion import (
    ConclusionLineageError,
    compile_investigation_conclusion,
)
from app.services.root_cause import run_single_level_investigation


def _request(**updates):
    request = {
        "investigation_id": "M6-test",
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
        "candidate_dimensions": ["country", "device", "customer_type"],
        "maximum_depth": 3,
        "minimum_rows_per_period_for_drill_down": 1,
        "conclusion_compilation_enabled": True,
    }
    request.update(updates)
    return request


def _rows_from_changes(cells):
    rows = []
    for country, device, customer_type, change in cells:
        rows.extend(
            [
                {
                    "date": "2026-01-01",
                    "country": country,
                    "device": device,
                    "customer_type": customer_type,
                    "revenue": 200.0,
                },
                {
                    "date": "2026-02-01",
                    "country": country,
                    "device": device,
                    "customer_type": customer_type,
                    "revenue": 200.0 + change,
                },
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
            {
                "date": f"{period}-01",
                "country": country,
                "device": device,
                "customer_type": customer_type,
                "revenue": total / count,
            }
        )


def _downstream_quality_rows():
    rows = []
    _add_group(rows, "2026-01", "Germany", "Mobile", "Returning", 6, 120)
    _add_group(rows, "2026-01", "Germany", "Mobile", "New", 4, 80)
    _add_group(rows, "2026-01", "Germany", "Desktop", "Returning", 3, 60)
    _add_group(rows, "2026-01", "Germany", "Desktop", "New", 2, 40)
    _add_group(rows, "2026-02", "Germany", "Mobile", "Returning", 3, 60)
    _add_group(rows, "2026-02", "Germany", "Mobile", "New", 2, 40)
    _add_group(rows, "2026-02", "Germany", "Desktop", "Returning", 6, 54)
    _add_group(rows, "2026-02", "Germany", "Desktop", "New", 4, 36)
    _add_group(rows, "2026-01", "France", "Mobile", "Returning", 8, 160)
    _add_group(rows, "2026-01", "France", "Desktop", "New", 7, 140)
    _add_group(rows, "2026-02", "France", "Mobile", "Returning", 8, 155)
    _add_group(rows, "2026-02", "France", "Desktop", "New", 7, 135)
    return rows


def test_recursive_conclusion_preserves_full_path_and_deepest_scope():
    state = run_single_level_investigation(
        pd.DataFrame(_recursive_rows()), _request()
    )
    conclusion = state.final_conclusion

    assert conclusion is not None
    assert conclusion.conclusion_path_node_ids == ("IN0", "IN1", "IN2", "IN3")
    assert [(item.dimension, item.segment) for item in conclusion.target_scope.filter_path] == [
        ("country", "Germany"),
        ("device", "Mobile"),
        ("customer_type", "Returning"),
    ]
    assert conclusion.target_scope.target_path_node_id == "IN3"
    assert conclusion.leading_dimension == "customer_type"
    assert conclusion.leading_segment == "Returning"
    assert conclusion.terminal_category == "bounded_by_max_depth"


def test_downstream_quality_block_keeps_valid_upstream_target():
    state = run_single_level_investigation(
        pd.DataFrame(_downstream_quality_rows()), _request()
    )
    conclusion = state.final_conclusion

    assert conclusion is not None
    assert conclusion.claim_type == "leading_tested_contributor"
    assert conclusion.readiness_status == "ready_with_caveats"
    assert conclusion.leading_dimension == "device"
    assert conclusion.leading_segment == "Mobile"
    assert conclusion.target_scope.target_path_node_id == "IN2"
    assert conclusion.terminal_category == "blocked_by_data_quality"
    assert "downstream_scope_data_quality" in conclusion.caveat_codes
    assert conclusion.readiness_checks.exact_scope_data_quality_safe is True
    assert conclusion.low_level_stops[-1].stopping_reason == "scoped_data_quality_failure"
    assert all(item.dimension != "customer_type" for item in conclusion.target_scope.filter_path)


def test_compiler_is_idempotent_and_does_not_mutate_state():
    disabled_request = _request(conclusion_compilation_enabled=False)
    state = run_single_level_investigation(
        pd.DataFrame(_recursive_rows()), disabled_request
    )
    original = deepcopy(state.model_dump(mode="json"))

    first = compile_investigation_conclusion(state, disabled_request)
    second = compile_investigation_conclusion(state, disabled_request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert state.model_dump(mode="json") == original
    assert state.final_conclusion is None


def test_global_data_quality_failure_compiles_exact_abstention():
    rows = _recursive_rows()
    unsafe = [item for item in rows if item["date"] == "2026-01-01"]
    unsafe.append(next(item for item in rows if item["date"] == "2026-02-01"))
    state = run_single_level_investigation(
        pd.DataFrame(unsafe), _request(maximum_depth=1)
    )

    conclusion = state.final_conclusion
    assert conclusion is not None
    assert conclusion.claim_type == "data_quality_abstention"
    assert conclusion.readiness_status == "not_ready_data_quality"
    assert conclusion.terminal_category == "blocked_by_data_quality"


def test_corrupt_conclusion_lineage_fails_closed():
    disabled_request = _request(conclusion_compilation_enabled=False)
    state = run_single_level_investigation(
        pd.DataFrame(_recursive_rows()), disabled_request
    )
    corrupt = state.model_copy(update={"evidence": state.evidence[:-1]})

    with pytest.raises(ConclusionLineageError):
        compile_investigation_conclusion(corrupt, disabled_request)


def test_compatibility_matrix_rejects_robust_claim_with_competing_status():
    state = run_single_level_investigation(
        pd.DataFrame(_recursive_rows()), _request()
    )
    payload = state.final_conclusion.model_dump(mode="json")
    payload.update(
        {
            "claim_type": "robust_descriptive_explanation",
            "robustness_status": "competing_explanations",
        }
    )

    with pytest.raises(ValidationError):
        InvestigationConclusion.model_validate(payload)


def test_compatibility_matrix_rejects_ready_with_blocking_exact_scope():
    state = run_single_level_investigation(
        pd.DataFrame(_recursive_rows()), _request()
    )
    payload = state.final_conclusion.model_dump(mode="json")
    payload["readiness_status"] = "ready"
    payload["readiness_checks"]["exact_scope_data_quality_safe"] = False

    with pytest.raises(ValidationError):
        InvestigationConclusion.model_validate(payload)


def test_feature_disabled_preserves_the_pre_milestone_state_shape():
    request = _request(conclusion_compilation_enabled=False)
    state = run_single_level_investigation(pd.DataFrame(_recursive_rows()), request)

    assert state.final_conclusion is None
