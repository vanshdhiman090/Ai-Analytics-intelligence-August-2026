from pathlib import Path

import pandas as pd
import pytest

from app.domain.contracts import AnalysisOperation, AnalysisPlan
from app.services.analysis import AnalysisPlanError, execute_plan, validate_evidence_integrity, validate_question_coverage
from app.domain.contracts import OperationResult
from app.services.tabular import process_dataset, profile_dataframe


def sales_frame():
    return pd.DataFrame(
        {
            "order_date": ["2026-01-01", "2026-01-02", "2026-02-01", "2026-02-01"],
            "region": ["North", "South", "North", "North"],
            "revenue": [100.0, 80.0, 140.0, 140.0],
            "units": [5, 4, 7, 7],
        }
    )


def test_profile_is_dataset_aware():
    profile = profile_dataframe(sales_frame())
    assert profile["row_count"] == 4
    assert profile["duplicate_row_count"] == 1
    assert profile["columns"]["order_date"]["semantic_type"] == "datetime"
    assert profile["columns"]["revenue"]["semantic_type"] == "numeric"


def test_profile_reports_placeholder_pct_separately_from_null_pct():
    frame = pd.DataFrame(
        {
            "region": ["North"] * 7 + ["Not Defined"] * 3,
        }
    )
    profile = profile_dataframe(frame)
    column = profile["columns"]["region"]
    assert column["null_count"] == 0
    assert column["null_pct"] == 0
    assert column["placeholder_count"] == 3
    assert column["placeholder_pct"] == pytest.approx(30.0)


def test_conservative_processing_removes_only_exact_duplicates(tmp_path: Path):
    source = tmp_path / "sales.csv"
    output = tmp_path / "cleaned.csv"
    sales_frame().to_csv(source, index=False)
    result = process_dataset(source, output)
    assert result.summary["rows_before"] == 4
    assert result.summary["rows_after"] == 3
    assert result.checklist["meaning_changing_imputation_performed"] is False
    assert output.exists()


def test_executor_handles_grouped_and_trend_operations():
    plan = AnalysisPlan(
        objective="Compare revenue by region and over time.",
        question_coverage=["Regional comparison", "Monthly movement"],
        operations=[
            AnalysisOperation(
                operation_id="OP1",
                kind="grouped_aggregate",
                metric_column="revenue",
                dimension_column="region",
                aggregation="sum",
                rationale="Compare regional contribution.",
            ),
            AnalysisOperation(
                operation_id="OP2",
                kind="trend",
                metric_column="revenue",
                time_column="order_date",
                aggregation="sum",
                rationale="Measure monthly movement.",
            ),
        ],
    )
    evidence = execute_plan(sales_frame(), plan)
    assert [item.evidence_id for item in evidence] == ["E1", "E2"]
    assert evidence[0].rows[0]["region"] == "North"
    assert evidence[1].rows[-1]["period"] == "2026-02"


def test_executor_handles_distribution_and_correlation_on_different_schema():
    survey = pd.DataFrame({"satisfaction": [1, 2, 3, 4, 5], "retention_days": [2, 4, 8, 14, 20]})
    plan = AnalysisPlan(
        objective="Assess satisfaction distribution and association with retention.",
        question_coverage=["Spread", "Association"],
        operations=[
            AnalysisOperation(
                operation_id="OP1",
                kind="distribution",
                metric_column="satisfaction",
                rationale="Inspect the observed spread.",
            ),
            AnalysisOperation(
                operation_id="OP2",
                kind="correlation",
                metric_column="satisfaction",
                dimension_column="retention_days",
                rationale="Measure association without claiming causation.",
            ),
        ],
    )
    evidence = execute_plan(survey, plan)
    assert evidence[0].rows[3]["quantile"] == 0.5
    assert evidence[1].rows[0]["correlation"] > 0.9
    assert "does not establish causation" in evidence[1].caveats[0]


def test_executor_rejects_model_invented_columns():
    plan = AnalysisPlan(
        objective="Invalid plan.",
        question_coverage=["Invalid"],
        operations=[
            AnalysisOperation(
                operation_id="OP1",
                kind="grouped_aggregate",
                metric_column="profit",
                dimension_column="region",
                aggregation="sum",
                rationale="This column does not exist.",
            )
        ],
    )
    with pytest.raises(AnalysisPlanError, match="unknown or missing column"):
        execute_plan(sales_frame(), plan)


def test_plan_must_cover_columns_explicitly_named_in_question():
    plan = AnalysisPlan(
        objective="Compare revenue by region.",
        question_coverage=["Revenue"],
        operations=[AnalysisOperation(operation_id="OP1", kind="grouped_aggregate", metric_column="revenue", dimension_column="region", aggregation="sum", rationale="Compare revenue")],
    )
    frame = sales_frame().assign(profit=[20.0, 10.0, 35.0, 35.0])
    with pytest.raises(AnalysisPlanError, match="profit"):
        validate_question_coverage(frame, plan, "Compare revenue and profit by region")


def test_grouped_sum_quantifies_rank_share_and_concentration():
    plan = AnalysisPlan(
        objective="Explain regional revenue contribution.",
        question_coverage=["Contribution by region"],
        operations=[AnalysisOperation(operation_id="OP1", kind="grouped_aggregate", metric_column="revenue", dimension_column="region", aggregation="sum", rationale="Size contribution")],
    )
    result = execute_plan(sales_frame(), plan)[0]
    assert result.rows[0]["rank"] == 1
    assert result.rows[0]["share_of_total_pct"] == pytest.approx(380 / 460 * 100)
    assert result.diagnostics["top_group_share_pct"] == pytest.approx(380 / 460 * 100)


def test_grouped_aggregate_preserves_highest_and_lowest_groups():
    frame = pd.DataFrame({"state": list("ABCDEF"), "units": [60, 50, 40, 30, 20, 10]})
    operation = AnalysisOperation(operation_id="OP1", kind="grouped_aggregate", metric_column="units", dimension_column="state", aggregation="sum", limit=4, rationale="Compare extremes")

    result = execute_plan(frame, AnalysisPlan(objective="Compare state extremes", question_coverage=["States"], operations=[operation]))[0]

    assert [row["state"] for row in result.rows] == ["A", "B", "E", "F"]
    assert result.rows[-1]["rank"] == 6


def test_grouped_aggregate_supports_two_dimension_intersections():
    frame = pd.DataFrame({"state": ["A", "A", "B", "B"], "product": ["Shoe", "Shirt", "Shoe", "Shirt"], "units": [10, 5, 8, 2]})
    operation = AnalysisOperation(operation_id="OP1", kind="grouped_aggregate", metric_column="units", dimension_column="state", secondary_dimension_column="product", aggregation="sum", rationale="Compare state-product intersections")

    result = execute_plan(frame, AnalysisPlan(objective="Compare intersections", question_coverage=["State and product"], operations=[operation]))[0]

    assert result.diagnostics["dimension_columns"] == ["state", "product"]
    assert {(row["state"], row["product"]) for row in result.rows} == {("A", "Shoe"), ("A", "Shirt"), ("B", "Shoe"), ("B", "Shirt")}


def test_period_comparison_calculates_absolute_and_percent_change():
    plan = AnalysisPlan(
        objective="Compare the latest monthly revenue with the prior month.",
        question_coverage=["Latest period comparison"],
        operations=[AnalysisOperation(operation_id="OP1", kind="period_comparison", metric_column="revenue", time_column="order_date", aggregation="sum", time_grain="month", rationale="Quantify change")],
    )
    result = execute_plan(sales_frame(), plan)[0]
    latest = result.rows[-1]
    assert latest["absolute_change"] == 100.0
    assert latest["percent_change"] == pytest.approx(100 / 180 * 100)
    assert result.quality_status == "caution"


def test_outlier_analysis_flags_values_but_never_removes_them():
    frame = pd.DataFrame({"value": [10, 11, 12, 12, 13, 14, 100]})
    plan = AnalysisPlan(
        objective="Identify unusual values for review.",
        question_coverage=["Outliers"],
        operations=[AnalysisOperation(operation_id="OP1", kind="outlier_analysis", metric_column="value", rationale="Flag unusual observations")],
    )
    result = execute_plan(frame, plan)[0]
    assert result.diagnostics["outlier_count"] == 1
    assert result.rows[1]["outlier_value"] == 100
    assert "must not be removed automatically" in result.caveats[0]


def test_correlation_rejects_constant_columns_and_flags_small_samples():
    constant = pd.DataFrame({"x": [1, 1, 1, 1], "y": [1, 2, 3, 4]})
    plan = AnalysisPlan(
        objective="Assess association.",
        question_coverage=["Association"],
        operations=[AnalysisOperation(operation_id="OP1", kind="correlation", metric_column="x", dimension_column="y", rationale="Measure association")],
    )
    with pytest.raises(AnalysisPlanError, match="variation"):
        execute_plan(constant, plan)


def test_time_question_requires_time_based_operation():
    plan = AnalysisPlan(
        objective="Summarize revenue.",
        question_coverage=["Revenue"],
        operations=[AnalysisOperation(operation_id="OP1", kind="distribution", metric_column="revenue", rationale="Describe revenue")],
    )
    with pytest.raises(AnalysisPlanError, match="time-based"):
        validate_question_coverage(sales_frame(), plan, "How did revenue change over time?")


def test_runtime_integrity_gate_rejects_non_reconciling_shares():
    invalid = OperationResult(
        evidence_id="E1", operation_id="OP1", kind="grouped_aggregate", title="Invalid shares",
        columns=["segment", "value", "share_of_total_pct", "rank"],
        rows=[{"segment":"A","value":80,"share_of_total_pct":80,"rank":1},{"segment":"B","value":20,"share_of_total_pct":30,"rank":2}],
        method="Injected regression fixture", population="2 rows", diagnostics={"group_count":2},
    )
    with pytest.raises(AnalysisPlanError, match="reconcile"):
        validate_evidence_integrity([invalid])


def test_runtime_integrity_gate_rejects_non_finite_values():
    invalid = OperationResult(
        evidence_id="E1", operation_id="OP1", kind="correlation", title="Invalid correlation",
        columns=["correlation"], rows=[{"correlation":float("inf")}], method="Injected regression fixture", population="2 rows",
    )
    with pytest.raises(AnalysisPlanError, match="non-finite"):
        validate_evidence_integrity([invalid])


def test_kpi_ratio_uses_ratio_of_sums_and_preserves_denominator():
    frame = pd.DataFrame({"channel":["A","A","B"],"conversions":[10,20,5],"visits":[100,50,100]})
    plan = AnalysisPlan(objective="Compare conversion rate", question_coverage=["Conversion rate"], operations=[AnalysisOperation(operation_id="OP1",kind="kpi_ratio",metric_column="conversions",denominator_column="visits",dimension_column="channel",ratio_scale=100,rationale="Use ratio of sums")])
    result = execute_plan(frame, plan)[0]
    assert result.rows[0]["channel"] == "A"
    assert result.rows[0]["ratio"] == pytest.approx(20.0)
    assert result.rows[0]["denominator"] == 150.0


def test_kpi_ratio_rejects_zero_denominator_everywhere():
    frame = pd.DataFrame({"wins":[1,2],"opportunities":[0,0]})
    plan = AnalysisPlan(objective="Calculate win rate",question_coverage=["Win rate"],operations=[AnalysisOperation(operation_id="OP1",kind="kpi_ratio",metric_column="wins",denominator_column="opportunities",rationale="Protect denominator")])
    with pytest.raises(AnalysisPlanError, match="zero denominator"):
        execute_plan(frame, plan)


def test_statistical_comparison_reports_effect_size_and_permutation_test():
    frame = pd.DataFrame({"group":["control"]*5+["variant"]*5,"value":[10,11,9,10,10,20,21,19,20,20]})
    plan = AnalysisPlan(objective="Compare variant with control",question_coverage=["Group difference"],operations=[AnalysisOperation(operation_id="OP1",kind="statistical_comparison",metric_column="value",dimension_column="group",baseline_value="control",comparison_value="variant",rationale="Measure magnitude and uncertainty")])
    result = execute_plan(frame, plan)[0]
    assert result.rows[0]["mean_difference"] == pytest.approx(10.0)
    assert result.rows[0]["cohens_d"] > 5
    assert 0 <= result.rows[0]["permutation_p_value"] <= 0.05
    assert result.quality_status == "caution"


def test_segment_change_reconciles_driver_contributions():
    frame = pd.DataFrame({"date":["2026-01-01","2026-01-01","2026-02-01","2026-02-01"],"segment":["A","B","A","B"],"sales":[100,100,150,80]})
    plan = AnalysisPlan(objective="Explain which segment drove sales change",question_coverage=["Change drivers"],operations=[AnalysisOperation(operation_id="OP1",kind="segment_change",metric_column="sales",dimension_column="segment",time_column="date",aggregation="sum",time_grain="month",rationale="Decompose change")])
    result = execute_plan(frame, plan)[0]
    assert result.diagnostics["total_change"] == 30.0
    assert result.rows[0]["segment"] == "A"
    assert result.rows[0]["absolute_change"] == 50
    assert result.diagnostics["reconciliation_residual"] == 0
