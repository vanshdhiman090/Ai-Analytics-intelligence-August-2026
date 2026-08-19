"""Deterministic tabular loading, profiling, and conservative cleaning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.domain.segment_labels import PLACEHOLDER_SEGMENT_LABELS


DATE_NAME_TOKENS = ("date", "time", "timestamp", "month", "quarter", "year")
DATE_PARSE_MIN_SUCCESS_RATE = 0.99

IDENTIFIER_NAME_PATTERN = re.compile(r"(^id$|_id$|^id_|identifier|uuid|_key$)")
IDENTIFIER_UNIQUENESS_RATIO = 0.9

# Numeric columns whose name signals a calendar/cyclical position (not an
# additive quantity). Cardinality must also fit that unit, so a "Month"
# column with 40 distinct values (not a calendar month) still falls through
# to quantity/discrete_scale rather than being misread as cyclical.
CYCLICAL_NAME_BOUNDS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("hour",), 24),
    (("day of week", "dayofweek", "weekday"), 7),
    (("month",), 12),
    (("quarter",), 4),
    (("week",), 53),
)

# Numeric columns that are neither an identifier nor a named calendar unit,
# but still have too few distinct values to be a summable quantity (rating
# scales, boolean-as-integer flags, tier levels). This is a cardinality
# heuristic only; a high-cardinality non-additive column such as a percentage
# or rate is a known, separate gap this milestone does not address.
DISCRETE_SCALE_MAX_UNIQUE = 15


def classify_numeric_role(series: pd.Series, name: str, row_count: int) -> str | None:
    """Classify a numeric column's business role for KPI/dimension eligibility.

    Returns one of "identifier", "cyclical", "discrete_scale", "quantity" for
    a numeric-dtype column, or None for a non-numeric column. Only "quantity"
    is safe to offer as a summable KPI.
    """
    if not pd.api.types.is_numeric_dtype(series):
        return None
    non_null = series.dropna()
    if non_null.empty:
        return "quantity"

    lowered = str(name).lower()
    unique_count = int(non_null.nunique())
    ratio = unique_count / row_count if row_count else 0.0

    if IDENTIFIER_NAME_PATTERN.search(lowered) or ratio >= IDENTIFIER_UNIQUENESS_RATIO:
        return "identifier"

    for tokens, bound in CYCLICAL_NAME_BOUNDS:
        if any(token in lowered for token in tokens) and unique_count <= bound:
            return "cyclical"

    if unique_count <= DISCRETE_SCALE_MAX_UNIQUE:
        return "discrete_scale"

    return "quantity"


class DateSemanticError(ValueError):
    """Raised when a date-like column has no safe, column-wide interpretation."""


@dataclass(frozen=True)
class DateParseResult:
    """The one governed interpretation of a source date column.

    Raw input is deliberately never replaced.  Consumers receive the parsed
    series only in memory and can inspect the decision recorded in ``metadata``.
    """

    parsed: pd.Series
    status: str
    detected_format: str | None
    confidence: str
    source_count: int
    parsed_count: int
    failed_count: int
    candidate_formats: tuple[str, ...] = ()

    @property
    def parse_rate(self) -> float:
        return self.parsed_count / self.source_count if self.source_count else 0.0

    def metadata(self) -> dict[str, Any]:
        valid = self.parsed.dropna()
        months = valid.dt.to_period("M") if not valid.empty else pd.Series(dtype="period[M]")
        observed_months = sorted(str(value) for value in months.unique())
        missing_months: list[str] = []
        if not valid.empty:
            expected = pd.period_range(valid.min().to_period("M"), valid.max().to_period("M"), freq="M")
            missing_months = [str(value) for value in expected if str(value) not in observed_months]
        return {
            "status": self.status,
            "detected_format": self.detected_format,
            "confidence": self.confidence,
            "source_non_null_count": self.source_count,
            "parsed_count": self.parsed_count,
            "failed_count": self.failed_count,
            "parse_rate": round(self.parse_rate, 6),
            "raw_values_preserved": True,
            "normalized_representation": "datetime64[ns] (in-memory only)",
            "min_date": json_value(valid.min()) if not valid.empty else None,
            "max_date": json_value(valid.max()) if not valid.empty else None,
            "observed_month_count": len(observed_months),
            "missing_months": missing_months,
            "candidate_formats": list(self.candidate_formats),
        }


_DATE_FORMATS: tuple[tuple[str, str], ...] = (
    ("YYYY-MM-DD", "%Y-%m-%d"),
    ("DD-MM-YYYY", "%d-%m-%Y"),
    ("MM-DD-YYYY", "%m-%d-%Y"),
    ("YYYY/MM/DD", "%Y/%m/%d"),
    ("DD/MM/YYYY", "%d/%m/%Y"),
    ("MM/DD/YYYY", "%m/%d/%Y"),
)


def _date_input(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return trimmed date input and its non-empty values without altering source data."""
    if pd.api.types.is_datetime64_any_dtype(series):
        normalized = pd.to_datetime(series, errors="coerce")
        return normalized, normalized.dropna()
    values = series.astype("string").str.strip().replace("", pd.NA)
    return values, values.dropna()


def infer_date_semantics(series: pd.Series) -> DateParseResult:
    """Infer one exact date format from a whole column; never guess ambiguous input."""
    values, non_null = _date_input(series)
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = values.astype("datetime64[ns]")
        return DateParseResult(parsed, "CONFIDENT_DATE_FORMAT", "NATIVE_DATETIME", "high", len(non_null), len(non_null), 0)
    if non_null.empty:
        return DateParseResult(pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]"), "INVALID_DATE_COLUMN", None, "none", 0, 0, 0)

    candidates: list[tuple[str, pd.Series]] = []
    for label, date_format in _DATE_FORMATS:
        parsed = pd.to_datetime(values, format=date_format, errors="coerce")
        if float(parsed.loc[non_null.index].notna().mean()) >= DATE_PARSE_MIN_SUCCESS_RATE:
            candidates.append((label, parsed))

    # ISO-8601 timestamp exports are unambiguous by their year-first shape.
    iso_timestamp = pd.to_datetime(values, format="ISO8601", errors="coerce")
    if float(iso_timestamp.loc[non_null.index].notna().mean()) >= DATE_PARSE_MIN_SUCCESS_RATE:
        candidates.append(("ISO-8601 timestamp", iso_timestamp))

    labels = tuple(label for label, _ in candidates)
    if len(candidates) == 1:
        label, parsed = candidates[0]
        parsed_count = int(parsed.loc[non_null.index].notna().sum())
        return DateParseResult(parsed, "CONFIDENT_DATE_FORMAT", label, "high", len(non_null), parsed_count, len(non_null) - parsed_count, labels)
    if len(candidates) > 1:
        # Multiple successful interpretations are safe only when every parsed
        # value is identical (for example an ISO value accepted by two parsers).
        first = candidates[0][1]
        equivalent = all(first.equals(candidate) for _, candidate in candidates[1:])
        if equivalent:
            label, parsed = candidates[0]
            parsed_count = int(parsed.loc[non_null.index].notna().sum())
            return DateParseResult(parsed, "CONFIDENT_DATE_FORMAT", label, "high", len(non_null), parsed_count, len(non_null) - parsed_count, labels)
        return DateParseResult(pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]"), "AMBIGUOUS_DATE_FORMAT", None, "none", len(non_null), 0, len(non_null), labels)

    # A named date column with mixed formats or unparseable strings must not be
    # coerced heuristically (pandas' mixed parser may interpret 01-02 two ways).
    return DateParseResult(pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]"), "INVALID_DATE_COLUMN", None, "none", len(non_null), 0, len(non_null), ())


def parse_date_series(series: pd.Series, *, column_name: str | None = None) -> pd.Series:
    """Return the central, strict parsed representation or a useful safe error."""
    result = infer_date_semantics(series)
    if result.status != "CONFIDENT_DATE_FORMAT":
        name = column_name or str(series.name) or "date column"
        raise DateSemanticError(
            f"{name} is {result.status}; no date interpretation was applied. "
            "Use an unambiguous, column-wide date format."
        )
    return result.parsed


def read_csv_robust(path: str | Path, nrows: int | None = None) -> pd.DataFrame:
    """Read common CSV exports deterministically, including European separators and Windows encodings."""
    source = Path(path)
    sample_bytes = source.read_bytes()[:131072]
    if b"\x00" in sample_bytes:
        raise ValueError("CSV contains binary null bytes")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            frame = pd.read_csv(source, sep=None, engine="python", encoding=encoding, nrows=nrows)
            if len(frame.columns) == 1:
                # Sniffing can choose a punctuation character inside free text. A
                # single-column CSV is still valid, so retry with a literal comma.
                comma_frame = pd.read_csv(source, sep=",", engine="python", encoding=encoding, nrows=nrows)
                if len(comma_frame.columns) > 1:
                    frame = comma_frame
            return frame
        except UnicodeDecodeError as exc:
            last_error = exc
        except pd.errors.ParserError:
            raise
        except Exception as exc:
            last_error = exc
    raise ValueError("CSV encoding is unsupported") from last_error


def load_dataframe(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return read_csv_robust(source)
    if suffix == ".xlsx":
        return pd.read_excel(source)
    raise ValueError(f"Unsupported dataset type: {suffix}")


def json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def infer_semantic_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    non_null = series.dropna()
    if non_null.empty:
        return "unknown"
    name_suggests_date = any(token in str(series.name).lower() for token in DATE_NAME_TOKENS)
    if name_suggests_date:
        date_semantics = infer_date_semantics(series)
        if date_semantics.status == "CONFIDENT_DATE_FORMAT":
            return "datetime"
        if date_semantics.status == "AMBIGUOUS_DATE_FORMAT":
            return "ambiguous_date"

    ratio = float(non_null.nunique() / len(non_null))
    return "categorical" if non_null.nunique() <= 50 or ratio <= 0.2 else "text"


def _placeholder_count(non_null: pd.Series) -> int:
    """Count non-null values whose stripped, lowercased label is a known placeholder.

    Distinct from null_count: this catches values a source system wrote in
    place of a real one ("Not Defined", "unknown", ...) rather than an
    actually-absent cell, so a wizard can warn about both independently.
    """
    if non_null.empty:
        return 0
    normalized = non_null.astype("string").str.strip().str.lower()
    return int(normalized.isin(PLACEHOLDER_SEGMENT_LABELS).sum())


def profile_dataframe(df: pd.DataFrame) -> dict:
    columns: dict[str, dict] = {}
    for name in df.columns:
        series = df[name]
        semantic_type = infer_semantic_type(series)
        non_null = series.dropna()
        placeholder_count = _placeholder_count(non_null)
        item = {
            "name": str(name),
            "dtype": str(series.dtype),
            "semantic_type": semantic_type,
            "numeric_role": classify_numeric_role(series, str(name), len(df)),
            "null_count": int(series.isna().sum()),
            "null_pct": round(float(series.isna().mean() * 100), 2),
            "placeholder_count": placeholder_count,
            "placeholder_pct": round(float(placeholder_count / len(series) * 100), 2) if len(series) else 0.0,
            "unique_count": int(series.nunique(dropna=True)),
            "sample_values": [json_value(value) for value in non_null.head(3).tolist()],
        }
        if semantic_type in {"datetime", "ambiguous_date"} or any(token in str(name).lower() for token in DATE_NAME_TOKENS):
            item["date_semantics"] = infer_date_semantics(series).metadata()
        if semantic_type == "numeric" and not non_null.empty:
            numeric = pd.to_numeric(non_null, errors="coerce").dropna()
            if not numeric.empty:
                item.update(
                    {
                        "min": json_value(numeric.min()),
                        "max": json_value(numeric.max()),
                        "mean": round(float(numeric.mean()), 4),
                        "median": round(float(numeric.median()), 4),
                    }
                )
        columns[str(name)] = item

    duplicate_count = int(df.duplicated().sum())
    all_null_columns = [str(column) for column in df.columns if df[column].isna().all()]
    constant_columns = [
        str(column) for column in df.columns if df[column].nunique(dropna=True) <= 1
    ]
    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "duplicate_row_count": duplicate_count,
        "all_null_columns": all_null_columns,
        "constant_columns": constant_columns,
        "columns": columns,
    }


def profile_dataset(path: str | Path) -> dict:
    return profile_dataframe(load_dataframe(path))


@dataclass(frozen=True)
class ProcessingResult:
    cleaned_path: Path
    checklist: dict
    cleaning_log: list[dict]
    integrity_checks: list[dict]
    validation_status: str
    findings: list[dict]
    summary: dict


def process_dataset(path: str | Path, output_path: Path) -> ProcessingResult:
    df = load_dataframe(path)
    rows_before = len(df)
    findings: list[dict] = []
    transformations: list[str] = []
    cleaning_log: list[dict] = []
    integrity_checks: list[dict] = []

    def log(action: str, columns: list[str], rows_affected: int, before: str, after: str, reason: str) -> None:
        cleaning_log.append({
            "log_id": f"CL{len(cleaning_log) + 1}",
            "action": action,
            "columns": ", ".join(columns) if columns else "All columns",
            "rows_affected": int(rows_affected),
            "before": before,
            "after": after,
            "reason": reason,
        })

    def check(name: str, status: str, detail: str, implication: str) -> None:
        integrity_checks.append({
            "check_id": f"IC{len(integrity_checks) + 1}",
            "check": name,
            "status": status,
            "detail": detail,
            "implication": implication,
        })

    duplicate_count = int(df.duplicated().sum())
    if duplicate_count:
        df = df.drop_duplicates().copy()
        transformations.append(f"Removed {duplicate_count} exact duplicate rows")
        log("Remove exact duplicate records", [str(item) for item in df.columns], duplicate_count, f"{rows_before} rows", f"{len(df)} rows", "Prevent exact records from being counted more than once")
        findings.append(
            {"column": "(all)", "issue": f"{duplicate_count} exact duplicate rows", "severity": "medium"}
        )

    text_columns = list(df.select_dtypes(include=["object", "string"]).columns)
    trimmed_columns: list[str] = []
    trimmed_cells = 0
    for column in text_columns:
        original = df[column]
        trimmed = original.map(lambda value: value.strip() if isinstance(value, str) else value)
        if not trimmed.equals(original):
            trimmed_cells += int((~(trimmed.eq(original) | (trimmed.isna() & original.isna()))).sum())
            df[column] = trimmed
            trimmed_columns.append(str(column))
    if trimmed_columns:
        transformations.append(f"Trimmed surrounding whitespace in: {', '.join(trimmed_columns)}")
        log("Standardize surrounding whitespace", trimmed_columns, trimmed_cells, "Text values may contain leading/trailing spaces", "Surrounding spaces removed", "Avoid false category splits while preserving text meaning")

    null_counts = df.isna().sum()
    for column, count in null_counts[null_counts > 0].items():
        findings.append(
            {
                "column": str(column),
                "issue": f"{int(count)} missing values retained for analytical handling",
                "severity": "medium" if count / max(len(df), 1) >= 0.2 else "low",
            }
        )

    duplicate_names = [str(name) for name in df.columns[df.columns.duplicated()].tolist()]
    check("Unique column names", "Fail" if duplicate_names else "Pass", f"Duplicate names: {duplicate_names}" if duplicate_names else "All column names are unique", "Duplicate field names make calculations ambiguous" if duplicate_names else "Columns can be referenced unambiguously")
    check("Row-count reconciliation", "Pass", f"{rows_before} input rows - {duplicate_count} exact duplicates = {len(df)} retained rows", "The transformation log reconciles to the exported row count")
    check("Exact duplicate control", "Pass", f"{int(df.duplicated().sum())} exact duplicates remain", "Exact records will not be counted twice")

    all_null_columns = [str(column) for column in df.columns if df[column].isna().all()]
    check("All-null fields", "Warning" if all_null_columns else "Pass", f"All-null columns: {all_null_columns}" if all_null_columns else "No all-null fields", "All-null fields cannot support analysis" if all_null_columns else "Every field contains at least one observed value")

    for column in [item for item in df.columns if str(item).lower().endswith(("id", "_key"))]:
        missing = int(df[column].isna().sum())
        duplicates = int(df[column].dropna().duplicated().sum())
        status = "Pass" if missing == 0 and duplicates == 0 else "Warning"
        check(f"Candidate key: {column}", status, f"{missing} missing and {duplicates} duplicate non-null values", "Candidate key appears unique and complete" if status == "Pass" else "Do not assume this field is a valid join key without review")

    for column in df.select_dtypes(include=["number"]).columns:
        negative = int((df[column] < 0).sum())
        if negative:
            check(f"Numeric sign review: {column}", "Warning", f"{negative} negative values observed", "Negative values may be valid; business-domain ranges were not supplied")

    for column in df.columns:
        if not (pd.api.types.is_datetime64_any_dtype(df[column]) or any(token in str(column).lower() for token in DATE_NAME_TOKENS)):
            continue
        semantics = infer_date_semantics(df[column])
        metadata = semantics.metadata()
        status = "Pass" if semantics.status == "CONFIDENT_DATE_FORMAT" else "Warning"
        detail = (
            f"{semantics.status}; format={semantics.detected_format or 'none'}; "
            f"{semantics.parse_rate:.1%} parsed ({semantics.parsed_count}/{semantics.source_count}); "
            f"range={metadata['min_date']} to {metadata['max_date']}; "
            f"missing months={len(metadata['missing_months'])}"
        )
        implication = "Dates were verified with a single column-wide format; raw values were retained" if status == "Pass" else "Date-dependent analysis is blocked until this source is made unambiguous"
        check(f"Date semantic audit: {column}", status, detail, implication)

    if not transformations:
        log("No automatic transformation", [], 0, f"{rows_before} rows", f"{len(df)} rows", "No exact duplicates or surrounding whitespace changes were detected")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    rows_after = len(df)
    validation_status = "Fail" if any(item["status"] == "Fail" for item in integrity_checks) else "Warning" if any(item["status"] == "Warning" for item in integrity_checks) else "Pass"
    return ProcessingResult(
        cleaned_path=output_path,
        checklist={
            "exact_duplicates_checked": True,
            "text_whitespace_standardized": trimmed_columns,
            "missing_values_profiled": True,
            "meaning_changing_imputation_performed": False,
            "derived_business_metrics_created": False,
            "transformations": transformations,
        },
        cleaning_log=cleaning_log,
        integrity_checks=integrity_checks,
        validation_status=validation_status,
        findings=findings,
        summary={
            "rows_before": int(rows_before),
            "rows_after": int(rows_after),
            "rows_removed": int(rows_before - rows_after),
            "notes": transformations or ["No automatic changes were required"],
            "validation_status": validation_status,
        },
    )
