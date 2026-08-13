from pathlib import Path

import pandas as pd
import pytest

from app.domain.contracts import AnalysisOperation
from app.services.analysis import AnalysisPlanError, execute_operation
from app.services.root_cause import build_root_cause_report
from app.services.comparison_context import extract_explicit_comparison_context
from app.services.tabular import (
    DateSemanticError,
    infer_date_semantics,
    load_dataframe,
    parse_date_series,
    process_dataset,
    profile_dataframe,
)


def _dates(values: list[str]) -> pd.Series:
    return pd.Series(values, name="Invoice Date")


def test_day_first_dates_are_confident_and_preserve_raw_source_values():
    source = _dates(["01-01-2020", "21-01-2020", "31-12-2021"])
    result = infer_date_semantics(source)

    assert result.status == "CONFIDENT_DATE_FORMAT"
    assert result.detected_format == "DD-MM-YYYY"
    assert result.parsed.dt.strftime("%Y-%m-%d").tolist() == ["2020-01-01", "2020-01-21", "2021-12-31"]
    assert result.metadata()["raw_values_preserved"] is True
    assert source.tolist() == ["01-01-2020", "21-01-2020", "31-12-2021"]


def test_month_first_and_iso_dates_are_supported_only_when_column_wide():
    month_first = infer_date_semantics(_dates(["01-21-2020", "12-31-2021"]))
    iso = infer_date_semantics(_dates(["2020-01-21", "2021-12-31"]))

    assert month_first.detected_format == "MM-DD-YYYY"
    assert iso.status == "CONFIDENT_DATE_FORMAT"
    assert iso.parsed.iloc[0] == pd.Timestamp("2020-01-21")


def test_ambiguous_and_mixed_date_columns_fail_closed():
    ambiguous = _dates(["01-02-2020", "02-03-2020"])
    mixed = _dates(["25-09-2021", "09-25-2021"])

    assert infer_date_semantics(ambiguous).status == "AMBIGUOUS_DATE_FORMAT"
    assert infer_date_semantics(mixed).status == "INVALID_DATE_COLUMN"
    assert profile_dataframe(ambiguous.to_frame())["columns"]["Invoice Date"]["semantic_type"] == "ambiguous_date"
    with pytest.raises(DateSemanticError, match="AMBIGUOUS_DATE_FORMAT"):
        parse_date_series(ambiguous)
    operation = AnalysisOperation(operation_id="OP1", kind="trend", metric_column="sales", time_column="Invoice Date", aggregation="sum", rationale="test")
    with pytest.raises(AnalysisPlanError, match="AMBIGUOUS_DATE_FORMAT"):
        execute_operation(pd.DataFrame({"Invoice Date": ambiguous, "sales": [1, 2]}), operation, "E1")


def test_rca_engine_preserves_an_explicit_month_pair_without_guessing():
    requested = extract_explicit_comparison_context(
        {"business_question": "Explain Total Sales from August 2021 to September 2021 by Region."}
    )
    explicit = extract_explicit_comparison_context(
        {"baseline_period": "2021-04", "comparison_period": "2021-05", "business_question": "August 2021 to September 2021"}
    )

    assert requested.model_dump() == {"baseline_period": "2021-08", "comparison_period": "2021-09", "period_granularity": "month", "period_source": "explicit_user_request", "metric": None}
    assert explicit.model_dump() == {"baseline_period": "2021-04", "comparison_period": "2021-05", "period_granularity": "month", "period_source": "explicit_user_request", "metric": None}


def test_processing_audits_dates_without_rewriting_raw_values(tmp_path: Path):
    source = tmp_path / "source.csv"
    output = tmp_path / "cleaned.csv"
    pd.DataFrame({"Invoice Date": ["01/02/2021", "02/03/2021"], "sales": [1, 2]}).to_csv(source, index=False)

    result = process_dataset(source, output)

    audit = next(item for item in result.integrity_checks if item["check"] == "Date semantic audit: Invoice Date")
    assert audit["status"] == "Warning"
    assert "AMBIGUOUS_DATE_FORMAT" in audit["detail"]
    assert pd.read_csv(output)["Invoice Date"].tolist() == ["01/02/2021", "02/03/2021"]


def _nike_source() -> Path:
    candidates = [
        Path(r"C:\Users\vansh\Downloads\Nike_Dataset.csv"),
        Path(r"C:\Users\vansh\Downloads\Nike Dataset.csv"),
    ]
    return next((path for path in candidates if path.is_file()), Path("__nike_benchmark_missing__.csv"))


@pytest.mark.skipif(not _nike_source().is_file(), reason="Nike benchmark source is not available on this machine")
def test_nike_benchmark_date_semantics_through_analysis_and_rca(tmp_path: Path):
    """Regression: do not reinterpret DD-MM-YYYY as month-first downstream."""
    source = _nike_source()
    cleaned = tmp_path / "cleaned.csv"
    process_dataset(source, cleaned)
    frame = load_dataframe(cleaned)
    profile = profile_dataframe(frame)
    date_metadata = profile["columns"]["Invoice Date"]["date_semantics"]
    assert date_metadata["status"] == "CONFIDENT_DATE_FORMAT"
    assert date_metadata["detected_format"] == "DD-MM-YYYY"
    assert date_metadata["parse_rate"] == 1.0
    assert date_metadata["missing_months"] == []

    trend = execute_operation(
        frame,
        AnalysisOperation(operation_id="OP1", kind="trend", metric_column="Total Sales", time_column="Invoice Date", aggregation="sum", time_grain="month", rationale="Nike benchmark"),
        "E1",
    )
    periods = {row["period"]: row for row in trend.rows}
    assert periods["2021-08"]["value"] == 681562
    assert periods["2021-09"]["value"] == 564937
    assert periods["2021-09"]["absolute_change"] == -116625
    assert periods["2021-09"]["percent_change"] == pytest.approx(-17.11, abs=0.01)

    rca = build_root_cause_report(
        frame,
        {"metric_name": "Total Sales", "metric_column": "Total Sales", "time_column": "Invoice Date", "driver_column": "Region", "time_grain": "month"},
        state={"baseline_period": "2021-08", "comparison_period": "2021-09", "period_completeness_confirmed": True},
    )
    assert rca["incident"]["baseline_value"] == 681562
    assert rca["incident"]["comparison_value"] == 564937
    assert rca["incident"]["absolute_change"] == -116625
    assert rca["incident"]["percent_change"] == pytest.approx(-17.11, abs=0.01)
