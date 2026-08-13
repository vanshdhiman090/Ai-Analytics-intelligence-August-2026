from pathlib import Path

import pandas as pd
import pytest

from app.domain.contracts import AnalysisOperation, AnalysisPlan
from app.agent.subagents.quality_specialists import CalculationReviewer
from app.services.analysis import apply_comparison_context, execute_plan
from app.services.comparison_context import extract_explicit_comparison_context
from app.services.root_cause import build_root_cause_report
from app.services.tabular import load_dataframe


def _nike() -> Path:
    path = Path(r"C:\Users\vansh\Downloads\Nike_Dataset.csv")
    if not path.is_file():
        pytest.skip("Nike benchmark source is not available on this machine")
    return path


def _context():
    return extract_explicit_comparison_context(
        {"business_question": "Why did Total Sales decrease in October 2021 compared with September 2021?"}
    )


def test_explicit_context_is_bound_to_period_and_segment_operations():
    context = _context()
    plan = AnalysisPlan(
        objective="Diagnose movement",
        question_coverage=["period", "region"],
        operations=[
            AnalysisOperation(operation_id="OP1", kind="period_comparison", metric_column="Total Sales", time_column="Invoice Date", aggregation="sum", rationale="movement"),
            AnalysisOperation(operation_id="OP2", kind="segment_change", metric_column="Total Sales", dimension_column="Region", time_column="Invoice Date", aggregation="sum", rationale="contribution"),
        ],
    )
    bound = apply_comparison_context(plan, context)
    assert {(item.baseline_period, item.comparison_period, item.period_source) for item in bound.operations} == {
        ("2021-09", "2021-10", "explicit_user_request")
    }


def test_nike_october_benchmark_uses_one_period_pair_everywhere():
    frame = load_dataframe(_nike())
    context = _context()
    dimensions = ["Product", "Retailer", "Sales Method", "Region"]
    operations = [
        AnalysisOperation(operation_id="OP1", kind="period_comparison", metric_column="Total Sales", time_column="Invoice Date", aggregation="sum", rationale="movement"),
        *[
            AnalysisOperation(operation_id=f"OP{index}", kind="segment_change", metric_column="Total Sales", dimension_column=dimension, time_column="Invoice Date", aggregation="sum", rationale="contribution")
            for index, dimension in enumerate(dimensions, start=2)
        ],
    ]
    evidence = execute_plan(frame, apply_comparison_context(AnalysisPlan(objective="RCA", question_coverage=["movement"], operations=operations), context))
    period = evidence[0]
    assert period.rows[0]["period"] == "2021-09"
    assert period.rows[1]["period"] == "2021-10"
    assert period.rows[0]["value"] == 564937
    assert period.rows[1]["value"] == 507084
    assert period.rows[1]["absolute_change"] == -57853
    assert period.rows[1]["percent_change"] == pytest.approx(-10.24, abs=.01)
    for item, dimension in zip(evidence[1:], dimensions):
        assert item.diagnostics["baseline_period"] == "2021-09", dimension
        assert item.diagnostics["comparison_period"] == "2021-10", dimension
        assert item.diagnostics["period_source"] == "explicit_user_request", dimension

    rca = build_root_cause_report(
        frame,
        {"metric_name": "Total Sales", "metric_column": "Total Sales", "time_column": "Invoice Date", "driver_column": "Region", "time_grain": "month"},
        evidence=[item.model_dump(mode="json") for item in evidence],
        state={"comparison_context": context.model_dump(mode="json"), "period_completeness_confirmed": True},
    )
    assert rca["incident"]["baseline_period"] == "2021-09"
    assert rca["incident"]["comparison_period"] == "2021-10"
    assert rca["incident"]["absolute_change"] == -57853


def test_automatic_latest_period_remains_when_no_context_is_supplied():
    frame = pd.DataFrame({"date": ["2021-09-01", "2021-10-01", "2021-11-01"], "segment": ["A"] * 3, "sales": [10, 8, 9]})
    plan = AnalysisPlan(objective="Latest", question_coverage=["movement"], operations=[AnalysisOperation(operation_id="OP1", kind="segment_change", metric_column="sales", dimension_column="segment", time_column="date", aggregation="sum", rationale="latest")])
    result = execute_plan(frame, plan)[0]
    assert result.diagnostics["baseline_period"] == "2021-10"
    assert result.diagnostics["comparison_period"] == "2021-11"
    assert result.diagnostics["period_source"] == "automatic_latest"


def test_explicit_non_adjacent_period_comparison_uses_governed_direction():
    frame = pd.DataFrame({"date": ["2021-09-01", "2021-10-01", "2021-11-01"], "sales": [10, 8, 9]})
    context = extract_explicit_comparison_context({"business_question": "Compare September 2021 with November 2021 sales."})
    plan = AnalysisPlan(objective="Comparison", question_coverage=["movement"], operations=[AnalysisOperation(operation_id="OP1", kind="period_comparison", metric_column="sales", time_column="date", aggregation="sum", rationale="pair")])
    rows = execute_plan(frame, apply_comparison_context(plan, context))[0].rows
    assert rows[1] == {"period": "2021-11", "value": 9, "previous_value": 10.0, "absolute_change": -1.0, "percent_change": -10.0}


def test_quality_reviewer_blocks_context_mismatch():
    decision = CalculationReviewer().review(
        {"comparison_context": {"baseline_period": "2021-09", "comparison_period": "2021-10"}, "evidence": [{"evidence_id": "E1", "kind": "segment_change", "diagnostics": {"baseline_period": "2021-11", "comparison_period": "2021-12"}}]},
        "analyze",
    )
    assert decision.status == "fail"
    assert decision.issues[0].code == "COMPARISON_CONTEXT_MISMATCH"
