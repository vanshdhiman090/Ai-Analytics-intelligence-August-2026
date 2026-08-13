"""Allow-listed analysis executor. No model-authored code is executed here."""

from __future__ import annotations

import re
from math import isfinite, sqrt

import numpy as np
import pandas as pd

from app.domain.contracts import AnalysisOperation, AnalysisPlan, OperationResult
from app.services.comparison_context import ComparisonContext
from app.services.tabular import DateSemanticError, json_value, parse_date_series


class AnalysisPlanError(ValueError):
    """Raised when a proposed operation is unsafe or incompatible with the data."""


def _normalized_words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower().replace("_", " "))


def question_referenced_columns(question: str, columns: list[str]) -> set[str]:
    """Find dataset columns explicitly named in the confirmed question."""
    question_words = _normalized_words(question)
    referenced: set[str] = set()
    for column in columns:
        words = _normalized_words(str(column))
        if not words:
            continue
        width = len(words)
        if any(question_words[index:index + width] == words for index in range(len(question_words) - width + 1)):
            referenced.add(str(column))
    return referenced


def validate_question_coverage(df: pd.DataFrame, plan: AnalysisPlan, question: str) -> None:
    """Reject plans that silently omit metrics explicitly requested by the user."""
    required = question_referenced_columns(question, [str(column) for column in df.columns])
    used = {
        value
        for operation in plan.operations
        for value in (operation.metric_column, operation.dimension_column, operation.secondary_dimension_column, operation.time_column)
        if value
    }
    missing = sorted(required - used)
    if missing:
        raise AnalysisPlanError(
            "The plan does not cover dataset columns explicitly named in the question: " + ", ".join(missing)
        )
    lowered = " ".join(_normalized_words(question))
    kinds = {operation.kind for operation in plan.operations}
    if any(phrase in lowered for phrase in ("over time", "trend", "change over", "month over month", "year over year")):
        if not kinds.intersection({"trend", "period_comparison"}):
            raise AnalysisPlanError("The question asks about change over time, but the plan has no time-based operation")
    if any(phrase in lowered for phrase in ("outlier", "unusual value", "anomal")):
        if not kinds.intersection({"distribution", "outlier_analysis"}):
            raise AnalysisPlanError("The question asks about unusual values or outliers, but the plan has no distribution diagnostic")


def require_column(df: pd.DataFrame, name: str | None, operation_id: str) -> str:
    if not name or name not in df.columns:
        raise AnalysisPlanError(f"{operation_id} references an unknown or missing column: {name}")
    return name


def require_numeric(df: pd.DataFrame, name: str | None, operation_id: str) -> str:
    column = require_column(df, name, operation_id)
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise AnalysisPlanError(f"{operation_id} requires numeric column '{column}'")
    return column


def records(frame: pd.DataFrame) -> list[dict]:
    return [
        {str(column): json_value(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _numeric_values(df: pd.DataFrame, name: str | None, operation_id: str) -> tuple[str, pd.Series, int]:
    column = require_numeric(df, name, operation_id)
    values = pd.to_numeric(df[column], errors="coerce")
    missing = int(values.isna().sum())
    return column, values.dropna(), missing


def _time_periods(values: pd.Series, requested: str) -> tuple[pd.Series, str]:
    valid = values.dropna()
    if valid.empty:
        return values.astype("string"), "month"
    grain = requested
    if grain == "auto":
        span_days = max(int((valid.max() - valid.min()).days), 0)
        grain = "day" if span_days <= 45 else "week" if span_days <= 180 else "month" if span_days <= 1095 else "quarter"
    if grain == "day":
        return values.dt.strftime("%Y-%m-%d"), grain
    if grain == "week":
        return values.dt.to_period("W").apply(lambda item: str(item.start_time.date()) if not pd.isna(item) else None), grain
    frequency = {"month": "M", "quarter": "Q", "year": "Y"}[grain]
    return values.dt.to_period(frequency).astype(str), grain


def apply_comparison_context(plan: AnalysisPlan, context: ComparisonContext | None) -> AnalysisPlan:
    """Bind a user-requested period pair to every time comparison in one plan."""
    if context is None:
        return plan
    operations = []
    for operation in plan.operations:
        if operation.kind in {"trend", "period_comparison", "segment_change"}:
            operations.append(operation.model_copy(update={
                "baseline_period": context.baseline_period,
                "comparison_period": context.comparison_period,
                "period_source": context.period_source,
                "time_grain": context.period_granularity,
            }))
        else:
            operations.append(operation)
    return plan.model_copy(update={"operations": operations})


def _comparison_periods(operation: AnalysisOperation, periods: list[str]) -> tuple[str, str, str]:
    explicit = operation.baseline_period or operation.comparison_period
    if explicit:
        if not operation.baseline_period or not operation.comparison_period:
            raise AnalysisPlanError(f"{operation.operation_id} has an incomplete explicit period context")
        baseline, comparison = operation.baseline_period, operation.comparison_period
        if baseline not in periods or comparison not in periods:
            raise AnalysisPlanError(f"{operation.operation_id} requested period context is not present in the data")
        if baseline == comparison:
            raise AnalysisPlanError(f"{operation.operation_id} baseline and comparison periods must differ")
        return baseline, comparison, "explicit_user_request"
    return periods[-2], periods[-1], "automatic_latest"


def _mean_ci(values: pd.Series) -> dict:
    count = int(len(values))
    if count < 2:
        return {"mean_ci_95_low": None, "mean_ci_95_high": None}
    mean = float(values.mean())
    margin = 1.96 * float(values.std(ddof=1)) / sqrt(count)
    return {"mean_ci_95_low": mean - margin, "mean_ci_95_high": mean + margin}


def _permutation_p_value(first: np.ndarray, second: np.ndarray, iterations: int = 2000) -> float:
    """Deterministic two-sided permutation test for a difference in means."""
    observed = abs(float(first.mean() - second.mean()))
    combined = np.concatenate([first, second])
    rng = np.random.default_rng(20260808)
    exceedances = 0
    for _ in range(iterations):
        shuffled = rng.permutation(combined)
        difference = abs(float(shuffled[: len(first)].mean() - shuffled[len(first):].mean()))
        exceedances += difference >= observed
    return (exceedances + 1) / (iterations + 1)


def execute_operation(df: pd.DataFrame, operation: AnalysisOperation, evidence_id: str) -> OperationResult:
    population = f"{len(df)} supplied rows before operation-level null filtering"
    caveats: list[str] = []
    diagnostics: dict = {}
    quality_status = "ready"

    if operation.kind == "summary":
        numeric = df.select_dtypes(include="number")
        if numeric.empty:
            raise AnalysisPlanError(f"{operation.operation_id} requested a numeric summary with no numeric columns")
        summary = numeric.describe().T.reset_index().rename(columns={"index": "metric"})
        summary = summary[["metric", "count", "mean", "std", "min", "25%", "50%", "75%", "max"]]
        result_rows = records(summary.head(operation.limit))
        title = "Numeric dataset summary"
        columns = list(summary.columns)
        method = "Pandas descriptive statistics on non-null numeric values"
        diagnostics = {"numeric_metric_count": int(len(numeric.columns)), "row_count": int(len(df))}

    elif operation.kind == "grouped_aggregate":
        dimension = require_column(df, operation.dimension_column, operation.operation_id)
        secondary_dimension = (
            require_column(df, operation.secondary_dimension_column, operation.operation_id)
            if operation.secondary_dimension_column else None
        )
        dimensions = [dimension] + ([secondary_dimension] if secondary_dimension else [])
        if operation.aggregation == "count" and not operation.metric_column:
            grouped = df.groupby(dimensions, dropna=False).size().reset_index(name="value")
            metric_label = "row count"
        else:
            metric = require_numeric(df, operation.metric_column, operation.operation_id)
            grouped = (
                df.groupby(dimensions, dropna=False)[metric]
                .agg(value=operation.aggregation, observed_count="count")
                .reset_index()
            )
            metric_label = f"{operation.aggregation} of {metric}"
        if "observed_count" not in grouped:
            grouped["observed_count"] = grouped["value"]
        grouped = grouped.sort_values("value", ascending=False)
        total = float(grouped["value"].sum()) if len(grouped) else 0.0
        if operation.aggregation in {"sum", "count"} and total != 0:
            grouped["share_of_total_pct"] = grouped["value"] / total * 100
        grouped["rank"] = np.arange(1, len(grouped) + 1)
        if len(grouped) > operation.limit:
            top_count = max(operation.limit // 2, 1)
            bottom_count = operation.limit - top_count
            displayed = pd.concat([grouped.head(top_count), grouped.tail(bottom_count)]).drop_duplicates()
        else:
            displayed = grouped
        result_rows = records(displayed)
        dimension_label = " × ".join(dimensions)
        title = f"{metric_label} by {dimension_label}"
        columns = [str(column) for column in displayed.columns]
        method = f"Grouped {operation.aggregation} by {dimension_label} with null groups retained; ranked across all observed groups"
        diagnostics = {
            "dimension_columns": dimensions,
            "group_count": int(len(grouped)),
            "displayed_group_count": int(len(displayed)),
            "top_group_share_pct": float(grouped.iloc[0]["share_of_total_pct"]) if "share_of_total_pct" in grouped and len(grouped) else None,
            "top_3_share_pct": float(grouped.head(3)["share_of_total_pct"].sum()) if "share_of_total_pct" in grouped else None,
        }
        if len(displayed) < len(grouped):
            caveats.append(
                f"Displayed {len(displayed)} of {len(grouped)} groups (highest and lowest); "
                "concentration diagnostics use all groups"
            )

    elif operation.kind in {"trend", "period_comparison"}:
        time_column = require_column(df, operation.time_column, operation.operation_id)
        metric = require_numeric(df, operation.metric_column, operation.operation_id)
        try:
            parsed_time = parse_date_series(df[time_column], column_name=time_column)
        except DateSemanticError as exc:
            raise AnalysisPlanError(str(exc)) from exc
        valid = df.loc[parsed_time.notna(), [metric]].copy()
        valid["period"], grain = _time_periods(parsed_time[parsed_time.notna()], operation.time_grain)
        if len(valid) < 2:
            raise AnalysisPlanError(f"{operation.operation_id} has insufficient valid dates")
        trend = valid.groupby("period")[metric].agg(operation.aggregation).reset_index(name="value")
        trend["previous_value"] = trend["value"].shift(1)
        trend["absolute_change"] = trend["value"] - trend["previous_value"]
        denominator = trend["previous_value"].replace(0, np.nan).abs()
        trend["percent_change"] = trend["absolute_change"] / denominator * 100
        available_periods = [str(value) for value in trend["period"].tolist()]
        if operation.kind == "period_comparison":
            baseline_period, comparison_period, period_source = _comparison_periods(operation, available_periods)
            selected = trend.set_index("period").loc[[baseline_period, comparison_period]].reset_index()
            # A governed pair can be non-adjacent.  Its displayed comparison
            # must always mean comparison minus baseline, never the preceding
            # observed period retained from the full trend calculation.
            selected.loc[selected["period"] == baseline_period, ["previous_value", "absolute_change", "percent_change"]] = [np.nan, np.nan, np.nan]
            baseline_value = float(selected.loc[selected["period"] == baseline_period, "value"].iloc[0])
            comparison_mask = selected["period"] == comparison_period
            comparison_value = selected.loc[comparison_mask, "value"].astype(float)
            selected.loc[comparison_mask, "previous_value"] = baseline_value
            selected.loc[comparison_mask, "absolute_change"] = comparison_value - baseline_value
            selected.loc[comparison_mask, "percent_change"] = (comparison_value - baseline_value) / abs(baseline_value) * 100 if baseline_value != 0 else np.nan
        else:
            selected = trend.tail(operation.limit)
            baseline_period, comparison_period, period_source = _comparison_periods(operation, available_periods) if operation.baseline_period else (None, None, None)
        result_rows = records(selected)
        title = f"{grain.title()}ly {operation.aggregation} of {metric}" if grain != "day" else f"Daily {operation.aggregation} of {metric}"
        if operation.kind == "period_comparison":
            title = f"{baseline_period} to {comparison_period} {grain}-over-{grain} comparison for {metric}"
        columns = ["period", "value", "previous_value", "absolute_change", "percent_change"]
        method = f"{grain.title()} grouped {operation.aggregation}; sequential change uses the immediately preceding observed period"
        latest = trend.iloc[-1]
        diagnostics = {
            "time_grain": grain,
            "period_count": int(len(trend)),
            "latest_period": str(latest["period"]),
            "latest_value": json_value(latest["value"]),
            "latest_absolute_change": json_value(latest["absolute_change"]),
            "latest_percent_change": json_value(latest["percent_change"]),
            "baseline_period": baseline_period,
            "comparison_period": comparison_period,
            "period_source": period_source,
        }
        if len(trend) < 3:
            quality_status = "caution"
            caveats.append("Fewer than 3 observed periods; this supports a comparison but not a stable trend conclusion")
        invalid_dates = int(parsed_time.isna().sum())
        if invalid_dates:
            caveats.append(f"Excluded {invalid_dates} rows with missing or invalid dates")

    elif operation.kind == "distribution":
        metric = require_numeric(df, operation.metric_column, operation.operation_id)
        values = df[metric].dropna()
        if values.empty:
            raise AnalysisPlanError(f"{operation.operation_id} has no valid numeric values")
        quantiles = values.quantile([0, 0.1, 0.25, 0.5, 0.75, 0.9, 1]).reset_index()
        quantiles.columns = ["quantile", "value"]
        result_rows = records(quantiles)
        title = f"Distribution of {metric}"
        columns = ["quantile", "value"]
        method = "Observed quantiles on non-null values"
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outlier_count = int(((values < lower) | (values > upper)).sum())
        diagnostics = {
            "valid_count": int(len(values)),
            "missing_count": int(df[metric].isna().sum()),
            "iqr": iqr,
            "outlier_count_iqr": outlier_count,
            "outlier_pct_iqr": outlier_count / len(values) * 100,
            **_mean_ci(values),
        }
        if len(values) < 30:
            quality_status = "caution"
            caveats.append("Fewer than 30 observations; distribution estimates may be unstable")

    elif operation.kind == "outlier_analysis":
        metric, values, missing = _numeric_values(df, operation.metric_column, operation.operation_id)
        if len(values) < 4:
            raise AnalysisPlanError(f"{operation.operation_id} needs at least 4 valid values for IQR outlier analysis")
        q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (values < lower) | (values > upper)
        outliers = values[mask].sort_values(ascending=False)
        result_rows = [{"metric": metric, "valid_count": len(values), "outlier_count": int(mask.sum()), "outlier_pct": float(mask.mean() * 100), "lower_bound": lower, "upper_bound": upper}]
        result_rows.extend({"metric": metric, "outlier_value": json_value(value)} for value in outliers.head(max(operation.limit - 1, 1)))
        title = f"IQR outlier diagnostic for {metric}"
        columns = sorted({key for row in result_rows for key in row})
        method = "Tukey 1.5×IQR rule on non-null numeric values; flags unusual observations, not errors"
        diagnostics = {"valid_count": len(values), "missing_count": missing, "outlier_count": int(mask.sum()), "outlier_pct": float(mask.mean() * 100), "lower_bound": lower, "upper_bound": upper}
        caveats.append("Flagged values require business review and must not be removed automatically")

    elif operation.kind == "kpi_ratio":
        numerator = require_numeric(df, operation.metric_column, operation.operation_id)
        denominator = require_numeric(df, operation.denominator_column, operation.operation_id)
        dimension = operation.dimension_column
        columns_to_use = [numerator, denominator] + ([require_column(df, dimension, operation.operation_id)] if dimension else [])
        valid = df[columns_to_use].dropna(subset=[numerator, denominator]).copy()
        if valid.empty:
            raise AnalysisPlanError(f"{operation.operation_id} has no complete numerator/denominator pairs")
        groups = valid.groupby(dimension, dropna=False) if dimension else [("Overall", valid)]
        result_rows = []
        zero_groups = []
        for label, group in groups:
            numerator_total = float(group[numerator].sum())
            denominator_total = float(group[denominator].sum())
            if denominator_total == 0:
                zero_groups.append(str(label))
                continue
            result_rows.append({
                **({str(dimension): json_value(label)} if dimension else {"scope": "Overall"}),
                "numerator": numerator_total,
                "denominator": denominator_total,
                "ratio": numerator_total / denominator_total * operation.ratio_scale,
                "complete_row_count": int(len(group)),
            })
        if not result_rows:
            raise AnalysisPlanError(f"{operation.operation_id} has zero denominator for every requested ratio")
        result_rows.sort(key=lambda row: row["ratio"], reverse=True)
        if zero_groups:
            caveats.append(f"Excluded {len(zero_groups)} group(s) with a zero denominator: {', '.join(zero_groups[:5])}")
            quality_status = "caution"
        excluded = int(len(df) - len(valid))
        if excluded:
            caveats.append(f"Excluded {excluded} rows missing the numerator or denominator")
        title = f"{numerator} per {denominator}" + (f" by {dimension}" if dimension else "")
        columns = list(result_rows[0].keys())
        method = f"Ratio of summed {numerator} to summed {denominator}, scaled by {operation.ratio_scale}; complete pairs only"
        diagnostics = {"scale": operation.ratio_scale, "complete_row_count": int(len(valid)), "excluded_row_count": excluded, "zero_denominator_group_count": len(zero_groups)}

    elif operation.kind == "statistical_comparison":
        metric = require_numeric(df, operation.metric_column, operation.operation_id)
        dimension = require_column(df, operation.dimension_column, operation.operation_id)
        if operation.baseline_value is None or operation.comparison_value is None:
            raise AnalysisPlanError(f"{operation.operation_id} requires explicit baseline_value and comparison_value")
        dimension_text = df[dimension].astype("string")
        baseline = pd.to_numeric(df.loc[dimension_text == operation.baseline_value, metric], errors="coerce").dropna()
        comparison = pd.to_numeric(df.loc[dimension_text == operation.comparison_value, metric], errors="coerce").dropna()
        if len(baseline) < 3 or len(comparison) < 3:
            raise AnalysisPlanError(f"{operation.operation_id} needs at least 3 valid observations in each comparison group")
        baseline_mean, comparison_mean = float(baseline.mean()), float(comparison.mean())
        mean_difference = comparison_mean - baseline_mean
        pooled_denominator = len(baseline) + len(comparison) - 2
        pooled_variance = (((len(baseline) - 1) * baseline.var(ddof=1)) + ((len(comparison) - 1) * comparison.var(ddof=1))) / pooled_denominator
        effect_size = mean_difference / sqrt(float(pooled_variance)) if pooled_variance > 0 else None
        p_value = _permutation_p_value(baseline.to_numpy(dtype=float), comparison.to_numpy(dtype=float))
        result_rows = [{
            "baseline_group": operation.baseline_value, "comparison_group": operation.comparison_value,
            "baseline_count": len(baseline), "comparison_count": len(comparison),
            "baseline_mean": baseline_mean, "comparison_mean": comparison_mean,
            "baseline_median": float(baseline.median()), "comparison_median": float(comparison.median()),
            "mean_difference": mean_difference,
            "percent_difference_vs_baseline": mean_difference / abs(baseline_mean) * 100 if baseline_mean != 0 else None,
            "cohens_d": effect_size, "permutation_p_value": p_value,
        }]
        title = f"Statistical comparison of {metric}: {operation.comparison_value} vs {operation.baseline_value}"
        columns = list(result_rows[0].keys())
        method = "Difference in means and medians, pooled-standard-deviation Cohen's d, and deterministic two-sided permutation test (2,000 resamples)"
        diagnostics = {"baseline_count": len(baseline), "comparison_count": len(comparison), "permutation_iterations": 2000, "effect_size": effect_size, "p_value": p_value}
        caveats.append("Statistical association between observed groups does not establish causal impact")
        if len(baseline) < 20 or len(comparison) < 20:
            quality_status = "caution"
            caveats.append("At least one group has fewer than 20 observations; treat inference as exploratory")

    elif operation.kind == "segment_change":
        metric = require_numeric(df, operation.metric_column, operation.operation_id)
        dimension = require_column(df, operation.dimension_column, operation.operation_id)
        time_column = require_column(df, operation.time_column, operation.operation_id)
        try:
            parsed_time = parse_date_series(df[time_column], column_name=time_column)
        except DateSemanticError as exc:
            raise AnalysisPlanError(str(exc)) from exc
        valid = df.loc[parsed_time.notna(), [dimension, metric]].copy()
        valid["period"], grain = _time_periods(parsed_time[parsed_time.notna()], operation.time_grain)
        periods = sorted(valid["period"].dropna().unique())
        if len(periods) < 2:
            raise AnalysisPlanError(f"{operation.operation_id} needs at least 2 valid periods for change decomposition")
        baseline_period, comparison_period, period_source = _comparison_periods(operation, [str(value) for value in periods])
        grouped = valid.groupby(["period", dimension], dropna=False)[metric].agg(operation.aggregation).unstack("period", fill_value=0)
        if baseline_period not in grouped or comparison_period not in grouped:
            raise AnalysisPlanError(f"{operation.operation_id} could not align the governed comparison periods")
        change = pd.DataFrame({dimension: grouped.index, "baseline_value": grouped[baseline_period].values, "comparison_value": grouped[comparison_period].values})
        change["absolute_change"] = change["comparison_value"] - change["baseline_value"]
        change["percent_change"] = change["absolute_change"] / change["baseline_value"].replace(0, np.nan).abs() * 100
        total_change = float(change["absolute_change"].sum())
        change["contribution_to_total_change_pct"] = change["absolute_change"] / total_change * 100 if total_change != 0 else np.nan
        change["absolute_contribution"] = change["absolute_change"].abs()
        change = change.sort_values("absolute_contribution", ascending=False).drop(columns="absolute_contribution")
        result_rows = records(change.head(operation.limit))
        title = f"{metric} change decomposition by {dimension}: {baseline_period} to {comparison_period}"
        columns = [str(column) for column in change.columns]
        method = f"{grain.title()} {operation.aggregation} by mutually exclusive segment; comparison period minus baseline period"
        diagnostics = {"time_grain": grain, "baseline_period": str(baseline_period), "comparison_period": str(comparison_period), "period_source": period_source, "segment_count": int(len(change)), "total_baseline": float(change['baseline_value'].sum()), "total_comparison": float(change['comparison_value'].sum()), "total_change": total_change, "reconciliation_residual": float(change['absolute_change'].sum() - total_change)}
        invalid_dates = int(parsed_time.isna().sum())
        if invalid_dates:
            caveats.append(f"Excluded {invalid_dates} rows with missing or invalid dates")
        if len(change) > operation.limit:
            caveats.append(f"Displayed {operation.limit} of {len(change)} segments; reconciliation uses all segments")
        caveats.append("The comparison period may be incomplete; confirm period completeness before operational decisions")
        quality_status = "caution"

    elif operation.kind == "correlation":
        first = require_numeric(df, operation.metric_column, operation.operation_id)
        second = require_numeric(df, operation.dimension_column, operation.operation_id)
        pair = df[[first, second]].dropna()
        if len(pair) < 3:
            raise AnalysisPlanError(f"{operation.operation_id} has fewer than 3 complete pairs")
        if pair[first].nunique() < 2 or pair[second].nunique() < 2:
            raise AnalysisPlanError(f"{operation.operation_id} requires variation in both correlation columns")
        value = float(pair[first].corr(pair[second]))
        strength = "very strong" if abs(value) >= .8 else "strong" if abs(value) >= .6 else "moderate" if abs(value) >= .4 else "weak" if abs(value) >= .2 else "very weak"
        result_rows = [{"metric_a": first, "metric_b": second, "correlation": value, "absolute_correlation": abs(value), "strength": strength, "direction": "positive" if value > 0 else "negative" if value < 0 else "none", "pair_count": len(pair)}]
        title = f"Correlation between {first} and {second}"
        columns = ["metric_a", "metric_b", "correlation", "pair_count"]
        method = "Pearson correlation on complete numeric pairs; correlation does not imply causation"
        caveats.append("Correlation does not establish causation")
        diagnostics = {"complete_pair_count": int(len(pair)), "excluded_pair_count": int(len(df) - len(pair)), "strength": strength}
        if len(pair) < 30:
            quality_status = "caution"
            caveats.append("Fewer than 30 complete pairs; treat the observed association as exploratory")

    else:
        raise AnalysisPlanError(f"Unsupported operation kind: {operation.kind}")

    return OperationResult(
        evidence_id=evidence_id,
        operation_id=operation.operation_id,
        kind=operation.kind,
        title=title,
        columns=columns,
        rows=result_rows,
        method=method,
        population=population,
        caveats=caveats,
        quality_status=quality_status,
        diagnostics=diagnostics,
    )


def execute_plan(df: pd.DataFrame, plan: AnalysisPlan) -> list[OperationResult]:
    operation_ids = [operation.operation_id for operation in plan.operations]
    if len(operation_ids) != len(set(operation_ids)):
        raise AnalysisPlanError("Analysis operation IDs must be unique")
    results = [
        execute_operation(df, operation, f"E{index}")
        for index, operation in enumerate(plan.operations, start=1)
    ]
    validate_evidence_integrity(results)
    return results


def validate_evidence_integrity(results: list[OperationResult]) -> None:
    """Fail closed when a calculation produces internally inconsistent evidence."""
    evidence_ids = [item.evidence_id for item in results]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise AnalysisPlanError("Evidence IDs must be unique")
    for item in results:
        for row in item.rows:
            for value in row.values():
                if isinstance(value, float) and not isfinite(value):
                    raise AnalysisPlanError(f"{item.operation_id} produced a non-finite numeric value")
        if item.kind == "grouped_aggregate":
            ranks = [row.get("rank") for row in item.rows]
            group_count = int(item.diagnostics.get("group_count") or len(ranks))
            if (
                ranks != sorted(ranks)
                or len(ranks) != len(set(ranks))
                or any(not isinstance(rank, int) or rank < 1 or rank > group_count for rank in ranks)
            ):
                raise AnalysisPlanError(f"{item.operation_id} produced inconsistent group ranks")
            shares = [row.get("share_of_total_pct") for row in item.rows]
            if all(value is not None for value in shares) and item.diagnostics.get("group_count") == len(item.rows):
                if abs(sum(float(value) for value in shares) - 100.0) > 1e-6:
                    raise AnalysisPlanError(f"{item.operation_id} contribution shares do not reconcile to 100%")
        elif item.kind in {"trend", "period_comparison"}:
            for row in item.rows:
                previous, value = row.get("previous_value"), row.get("value")
                if previous is None:
                    continue
                expected = float(value) - float(previous)
                if abs(float(row.get("absolute_change")) - expected) > 1e-9:
                    raise AnalysisPlanError(f"{item.operation_id} period change does not reconcile")
        elif item.kind == "distribution":
            quantiles = [float(row["quantile"]) for row in item.rows]
            values = [float(row["value"]) for row in item.rows]
            if quantiles != sorted(quantiles) or values != sorted(values):
                raise AnalysisPlanError(f"{item.operation_id} distribution quantiles are not monotonic")
        elif item.kind == "correlation":
            correlation = float(item.rows[0]["correlation"])
            if not -1.0 <= correlation <= 1.0:
                raise AnalysisPlanError(f"{item.operation_id} correlation is outside [-1, 1]")
        elif item.kind == "kpi_ratio":
            for row in item.rows:
                expected = float(row["numerator"]) / float(row["denominator"]) * float(item.diagnostics["scale"])
                if abs(float(row["ratio"]) - expected) > 1e-9:
                    raise AnalysisPlanError(f"{item.operation_id} ratio does not reconcile to its numerator and denominator")
        elif item.kind == "statistical_comparison":
            p_value = float(item.rows[0]["permutation_p_value"])
            if not 0.0 <= p_value <= 1.0:
                raise AnalysisPlanError(f"{item.operation_id} produced an invalid permutation p-value")
        elif item.kind == "segment_change":
            if abs(float(item.diagnostics.get("reconciliation_residual", 0))) > 1e-9:
                raise AnalysisPlanError(f"{item.operation_id} segment changes do not reconcile to the total change")
