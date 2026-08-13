"""Build a portable, reproducible project-files bundle for a completed analysis."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _analysis_script() -> str:
    """Return deterministic code that reproduces the allow-listed analysis plan."""
    return '''"""Reproduce the approved analysis from the cleaned dataset."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "cleaned.csv"
PLAN_PATH = PROJECT_ROOT / "config" / "analysis_plan.json"
OUTPUT_DIR = PROJECT_ROOT / "outputs"


def _require_column(frame: pd.DataFrame, name: str | None, operation_id: str) -> str:
    if not name or name not in frame.columns:
        raise ValueError(f"{operation_id} references an unknown column: {name}")
    return name


def _require_numeric(frame: pd.DataFrame, name: str | None, operation_id: str) -> str:
    column = _require_column(frame, name, operation_id)
    if not pd.api.types.is_numeric_dtype(frame[column]):
        raise ValueError(f"{operation_id} requires numeric column: {column}")
    return column


def _parse_date_series(series: pd.Series, column_name: str) -> pd.Series:
    """Strict reproduction of the agent's column-wide date semantic rule."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(series, errors="coerce")
    values = series.astype("string").str.strip().replace("", pd.NA)
    non_null = values.dropna()
    candidates = []
    for label, date_format in (("YYYY-MM-DD", "%Y-%m-%d"), ("DD-MM-YYYY", "%d-%m-%Y"), ("MM-DD-YYYY", "%m-%d-%Y"), ("YYYY/MM/DD", "%Y/%m/%d"), ("DD/MM/YYYY", "%d/%m/%Y"), ("MM/DD/YYYY", "%m/%d/%Y")):
        parsed = pd.to_datetime(values, format=date_format, errors="coerce")
        if len(non_null) and float(parsed.loc[non_null.index].notna().mean()) >= .99:
            candidates.append((label, parsed))
    iso = pd.to_datetime(values, format="ISO8601", errors="coerce")
    if len(non_null) and float(iso.loc[non_null.index].notna().mean()) >= .99:
        candidates.append(("ISO-8601 timestamp", iso))
    if len(candidates) == 1 or (len(candidates) > 1 and all(candidates[0][1].equals(item[1]) for item in candidates[1:])):
        return candidates[0][1]
    raise ValueError(f"{column_name} has no unambiguous column-wide date format; reproduction stopped safely.")


def execute_operation(frame: pd.DataFrame, operation: dict) -> pd.DataFrame:
    operation_id = operation["operation_id"]
    kind = operation["kind"]
    aggregation = operation.get("aggregation") or "mean"
    limit = int(operation.get("limit") or 50)

    if kind == "summary":
        numeric = frame.select_dtypes(include="number")
        if numeric.empty:
            raise ValueError(f"{operation_id} found no numeric columns")
        return numeric.describe().T.reset_index().rename(columns={"index": "metric"}).head(limit)

    if kind == "grouped_aggregate":
        dimension = _require_column(frame, operation.get("dimension_column"), operation_id)
        metric_name = operation.get("metric_column")
        if aggregation == "count" and not metric_name:
            result = frame.groupby(dimension, dropna=False).size().reset_index(name="value")
        else:
            metric = _require_numeric(frame, metric_name, operation_id)
            result = frame.groupby(dimension, dropna=False)[metric].agg(value=aggregation, observed_count="count").reset_index()
        if "observed_count" not in result:
            result["observed_count"] = result["value"]
        result = result.sort_values("value", ascending=False)
        total = float(result["value"].sum()) if len(result) else 0.0
        if aggregation in {"sum", "count"} and total != 0:
            result["share_of_total_pct"] = result["value"] / total * 100
        result["rank"] = np.arange(1, len(result) + 1)
        return result.head(limit)

    if kind in {"trend", "period_comparison"}:
        time_column = _require_column(frame, operation.get("time_column"), operation_id)
        metric = _require_numeric(frame, operation.get("metric_column"), operation_id)
        parsed_time = _parse_date_series(frame[time_column], time_column)
        valid = frame.loc[parsed_time.notna(), [metric]].copy()
        grain = operation.get("time_grain") or "month"
        if grain == "auto":
            span = int((parsed_time.max() - parsed_time.min()).days)
            grain = "day" if span <= 45 else "week" if span <= 180 else "month" if span <= 1095 else "quarter"
        if grain == "day":
            valid["period"] = parsed_time[parsed_time.notna()].dt.strftime("%Y-%m-%d")
        elif grain == "week":
            valid["period"] = parsed_time[parsed_time.notna()].dt.to_period("W").apply(lambda value: str(value.start_time.date()))
        else:
            valid["period"] = parsed_time[parsed_time.notna()].dt.to_period({"month": "M", "quarter": "Q", "year": "Y"}[grain]).astype(str)
        result = valid.groupby("period")[metric].agg(aggregation).reset_index(name="value")
        result["previous_value"] = result["value"].shift(1)
        result["absolute_change"] = result["value"] - result["previous_value"]
        result["percent_change"] = result["absolute_change"] / result["previous_value"].replace(0, np.nan).abs() * 100
        return result.tail(2 if kind == "period_comparison" else limit)

    if kind == "distribution":
        metric = _require_numeric(frame, operation.get("metric_column"), operation_id)
        values = frame[metric].dropna()
        result = values.quantile([0, .1, .25, .5, .75, .9, 1]).reset_index()
        result.columns = ["quantile", "value"]
        return result

    if kind == "correlation":
        first = _require_numeric(frame, operation.get("metric_column"), operation_id)
        second = _require_numeric(frame, operation.get("dimension_column"), operation_id)
        pair = frame[[first, second]].dropna()
        return pd.DataFrame([{
            "metric_a": first,
            "metric_b": second,
            "correlation": float(pair[first].corr(pair[second])),
            "pair_count": len(pair),
        }])

    if kind == "kpi_ratio":
        numerator = _require_numeric(frame, operation.get("metric_column"), operation_id)
        denominator = _require_numeric(frame, operation.get("denominator_column"), operation_id)
        dimension = operation.get("dimension_column")
        columns = [numerator, denominator] + ([_require_column(frame, dimension, operation_id)] if dimension else [])
        valid = frame[columns].dropna(subset=[numerator, denominator])
        groups = valid.groupby(dimension, dropna=False) if dimension else [("Overall", valid)]
        rows = []
        for label, group in groups:
            numerator_total, denominator_total = float(group[numerator].sum()), float(group[denominator].sum())
            if denominator_total == 0:
                continue
            rows.append({**({dimension: label} if dimension else {"scope": "Overall"}), "numerator": numerator_total, "denominator": denominator_total, "ratio": numerator_total / denominator_total * float(operation.get("ratio_scale") or 100), "complete_row_count": len(group)})
        return pd.DataFrame(rows).sort_values("ratio", ascending=False)

    if kind == "statistical_comparison":
        metric = _require_numeric(frame, operation.get("metric_column"), operation_id)
        dimension = _require_column(frame, operation.get("dimension_column"), operation_id)
        baseline_name, comparison_name = operation.get("baseline_value"), operation.get("comparison_value")
        labels = frame[dimension].astype("string")
        baseline = frame.loc[labels == baseline_name, metric].dropna().astype(float)
        comparison = frame.loc[labels == comparison_name, metric].dropna().astype(float)
        difference = float(comparison.mean() - baseline.mean())
        pooled = (((len(baseline)-1)*baseline.var(ddof=1))+((len(comparison)-1)*comparison.var(ddof=1))) / (len(baseline)+len(comparison)-2)
        combined = np.concatenate([baseline.to_numpy(), comparison.to_numpy()])
        rng, exceedances, iterations = np.random.default_rng(20260808), 0, 2000
        for _ in range(iterations):
            shuffled = rng.permutation(combined)
            exceedances += abs(float(shuffled[:len(baseline)].mean()-shuffled[len(baseline):].mean())) >= abs(difference)
        return pd.DataFrame([{"baseline_group":baseline_name,"comparison_group":comparison_name,"baseline_count":len(baseline),"comparison_count":len(comparison),"baseline_mean":float(baseline.mean()),"comparison_mean":float(comparison.mean()),"baseline_median":float(baseline.median()),"comparison_median":float(comparison.median()),"mean_difference":difference,"percent_difference_vs_baseline":difference/abs(float(baseline.mean()))*100 if baseline.mean()!=0 else None,"cohens_d":difference/np.sqrt(pooled) if pooled>0 else None,"permutation_p_value":(exceedances+1)/(iterations+1)}])

    if kind == "segment_change":
        metric = _require_numeric(frame, operation.get("metric_column"), operation_id)
        dimension = _require_column(frame, operation.get("dimension_column"), operation_id)
        time_column = _require_column(frame, operation.get("time_column"), operation_id)
        parsed = _parse_date_series(frame[time_column], time_column)
        valid = frame.loc[parsed.notna(), [dimension, metric]].copy()
        grain = operation.get("time_grain") or "month"
        if grain == "auto": grain = "month"
        valid["period"] = parsed[parsed.notna()].dt.to_period({"day":"D","week":"W","month":"M","quarter":"Q","year":"Y"}[grain]).astype(str)
        periods = sorted(valid["period"].unique())
        baseline_period, comparison_period = periods[-2], periods[-1]
        grouped = valid.groupby(["period",dimension],dropna=False)[metric].agg(aggregation).unstack("period",fill_value=0)
        result = pd.DataFrame({dimension:grouped.index,"baseline_value":grouped[baseline_period].values,"comparison_value":grouped[comparison_period].values})
        result["absolute_change"] = result["comparison_value"]-result["baseline_value"]
        result["percent_change"] = result["absolute_change"]/result["baseline_value"].replace(0,np.nan).abs()*100
        total_change = result["absolute_change"].sum()
        result["contribution_to_total_change_pct"] = result["absolute_change"]/total_change*100 if total_change != 0 else np.nan
        return result.reindex(result["absolute_change"].abs().sort_values(ascending=False).index).head(limit)

    if kind == "outlier_analysis":
        metric = _require_numeric(frame, operation.get("metric_column"), operation_id)
        values = frame[metric].dropna()
        q1, q3 = float(values.quantile(.25)), float(values.quantile(.75))
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = values[(values < lower) | (values > upper)].sort_values(ascending=False)
        rows = [{"metric": metric, "valid_count": len(values), "outlier_count": len(outliers), "outlier_pct": len(outliers) / len(values) * 100, "lower_bound": lower, "upper_bound": upper}]
        rows.extend({"metric": metric, "outlier_value": value} for value in outliers.head(max(limit - 1, 1)))
        return pd.DataFrame(rows)

    raise ValueError(f"Unsupported operation kind: {kind}")


def run_analysis() -> dict[str, pd.DataFrame]:
    frame = pd.read_csv(DATA_PATH)
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for index, operation in enumerate(plan.get("operations", []), start=1):
        evidence_id = f"E{index}"
        result = execute_operation(frame, operation)
        result.to_csv(OUTPUT_DIR / f"{evidence_id.lower()}-reproduced.csv", index=False)
        results[evidence_id] = result
    return results


if __name__ == "__main__":
    completed = run_analysis()
    print(f"Reproduced {len(completed)} evidence result(s).")
'''


def _notebook(state: Mapping[str, Any]) -> dict[str, Any]:
    summary = str(state.get("analysis_summary") or "No summary was produced.")
    findings = state.get("findings") or []
    finding_lines = "\n".join(
        f"- **{item.get('finding_id', 'Finding')}:** {item.get('statement', '')}"
        for item in findings
    ) or "- No validated finding was produced."
    recommendations = (state.get("action_package") or {}).get("recommendations") or state.get("recommendations") or []
    recommendation_lines = "\n".join(
        f"- {item.get('action', '')} (Owner: {item.get('owner_role', 'Not specified')}; timeframe: {item.get('timeframe', 'Not specified')})"
        for item in recommendations
    ) or "- No defensible action was produced."
    limitations = (state.get("action_package") or {}).get("limitations") or state.get("limitations") or []
    limitation_lines = "\n".join(f"- {item}" for item in limitations) or "- None recorded."
    question = str(state.get("business_question") or "Analysis question")
    source = str((state.get("roccc_answers") or {}).get("source_license") or "Source status not supplied")

    def markdown(source_text: str) -> dict[str, Any]:
        return {"cell_type": "markdown", "metadata": {}, "source": [line + "\n" for line in source_text.splitlines()]}

    def code(source_text: str) -> dict[str, Any]:
        return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": [line + "\n" for line in source_text.splitlines()]}

    return {
        "cells": [
            markdown(f"# Reproducible Case Study Analysis\n\n## tl;dr\n\n**Question:** {question}\n\n**Bottom line:** {summary}\n\n{finding_lines}"),
            markdown(f"## Context & Methods\n\nThis notebook reruns the approved, allow-listed calculations on `data/cleaned.csv`. It does not execute model-written code.\n\n### Key Assumptions\n\n- The cleaned CSV is the analysis-ready dataset used by the agent.\n- Results are descriptive unless explicitly supported otherwise.\n- Source and permission statement: {source}"),
            code("from pathlib import Path\nimport sys\nimport pandas as pd\n\nPROJECT_ROOT = Path.cwd()\nif not (PROJECT_ROOT / 'data' / 'cleaned.csv').exists():\n    raise FileNotFoundError('Run this notebook from the extracted project-files folder.')\nsys.path.insert(0, str(PROJECT_ROOT))"),
            markdown("## Data\n\nLoad the cleaned dataset and inspect a bounded preview."),
            code("data = pd.read_csv(PROJECT_ROOT / 'data' / 'cleaned.csv')\nprint(f'Rows: {len(data):,} | Columns: {len(data.columns):,}')\ndata.head(10)"),
            code("quality_summary = pd.DataFrame({\n    'dtype': data.dtypes.astype(str),\n    'null_count': data.isna().sum(),\n    'unique_count': data.nunique(dropna=True),\n})\nquality_summary"),
            markdown("## Results\n\nExecute the exact approved operation plan and save one CSV per evidence record under `outputs/`."),
            code("from src.reproduce_analysis import run_analysis\n\nreproduced = run_analysis()\nfor evidence_id, result in reproduced.items():\n    print(f'\\n{evidence_id}')\n    display(result)"),
            markdown(f"## Takeaways\n\n{finding_lines}\n\n### Recommended Actions\n\n{recommendation_lines}\n\n### Limitations\n\n{limitation_lines}"),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
            "analysis": {"execution_status": "ready_to_run", "source": "validated_agent_state"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def create_project_bundle(state: Mapping[str, Any], artifact_dir: Path) -> Path:
    """Create a ZIP containing the reproducible notebook, code, data, and evidence."""
    cleaned_path = Path(str(state.get("cleaned_path") or ""))
    if not cleaned_path.is_file():
        raise FileNotFoundError("The cleaned dataset is unavailable for the project-files bundle.")

    raw_reference = {
        "original_filename": state.get("original_filename") or "Not recorded",
        "sha256": state.get("source_sha256") or "Not recorded",
        "raw_file_included": False,
        "reason": "The original upload is referenced, not duplicated, to avoid unnecessary redistribution of raw data.",
        "source_register": state.get("source_register") or [],
        "roccc_assessment": state.get("roccc_answers") or {},
    }
    readme = f"""CASE STUDY PROJECT FILES

Question
{state.get('business_question') or 'Not recorded'}

Contents
- analysis.ipynb: reader-friendly reproducible notebook
- src/reproduce_analysis.py: full deterministic analysis code
- data/cleaned.csv: analysis-ready dataset
- data/raw-data-reference.json: original-file identity, hash, source and permission notes
- config/analysis_plan.json: approved calculation plan
- charts/: visuals generated from validated evidence
- outputs/: validated evidence/findings plus reproduced CSVs after execution

Run
1. Extract this ZIP.
2. Open a terminal in the extracted folder.
3. Install Python, pandas, and Jupyter if needed.
4. Run: python src/reproduce_analysis.py
5. Open: jupyter notebook analysis.ipynb

Validation status
The notebook structure and Python source were validated when this bundle was created. The notebook is intentionally distributed without hidden cached execution state; rerun it against the included cleaned data.
"""
    # Stage the expanded project in the short system temp directory. Creating
    # it below the run folder exceeds MAX_PATH on common Windows/OneDrive
    # installations even though the final ZIP itself fits safely.
    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = artifact_dir / "files.zip"
    with tempfile.TemporaryDirectory(prefix="analytics-project-") as staging:
        project_dir = Path(staging)
        (project_dir / "data").mkdir()
        (project_dir / "charts").mkdir()
        (project_dir / "config").mkdir()
        (project_dir / "outputs").mkdir()
        (project_dir / "src").mkdir()

        shutil.copy2(cleaned_path, project_dir / "data" / "cleaned.csv")
        for evidence_id, source_path in (state.get("chart_paths") or {}).items():
            source = Path(str(source_path))
            if source.is_file():
                shutil.copy2(source, project_dir / "charts" / f"{str(evidence_id).lower()}{source.suffix.lower()}")

        (project_dir / "src" / "__init__.py").write_text("", encoding="utf-8")
        script = _analysis_script()
        compile(script, "reproduce_analysis.py", "exec")
        (project_dir / "src" / "reproduce_analysis.py").write_text(script, encoding="utf-8")
        (project_dir / "analysis.ipynb").write_text(_json(_notebook(state)), encoding="utf-8")
        (project_dir / "config" / "analysis_plan.json").write_text(_json(state.get("analysis_plan") or {}), encoding="utf-8")
        (project_dir / "outputs" / "validated_evidence.json").write_text(_json(state.get("evidence") or []), encoding="utf-8")
        (project_dir / "outputs" / "validated_findings.json").write_text(_json(state.get("findings") or []), encoding="utf-8")
        (project_dir / "data" / "raw-data-reference.json").write_text(_json(raw_reference), encoding="utf-8")
        (project_dir / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(project_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(project_dir))
    return bundle_path
