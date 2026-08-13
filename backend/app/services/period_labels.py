"""Canonical period labels shared by the RCA engine and public API."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

import pandas as pd


PeriodGrain = Literal["day", "week", "month", "quarter", "year"]

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$")
_YEAR = re.compile(r"^\d{4}$")


def format_period_values(values: pd.Series, grain: PeriodGrain) -> pd.Series:
    """Format parsed dates exactly as the RCA engine's canonical periods."""
    if grain == "day":
        return values.dt.strftime("%Y-%m-%d")
    if grain == "week":
        return values.dt.to_period("W").apply(
            lambda item: str(item.start_time.date()) if not pd.isna(item) else None
        )
    frequency = {"month": "M", "quarter": "Q", "year": "Y"}[grain]
    return values.dt.to_period(frequency).astype(str)


def validate_period_label(label: str, grain: PeriodGrain) -> str:
    """Return a canonical label or raise for syntax incompatible with the engine."""
    if grain in {"day", "week"}:
        try:
            parsed = date.fromisoformat(label)
        except ValueError as exc:
            raise ValueError(f"{grain.title()} periods must use a valid YYYY-MM-DD date") from exc
        if label != parsed.isoformat():
            raise ValueError(f"{grain.title()} periods must use YYYY-MM-DD")
        if grain == "week":
            canonical = format_period_values(
                pd.Series(pd.to_datetime([label])), "week"
            ).iloc[0]
            if canonical != label:
                raise ValueError(
                    "Week periods must use YYYY-MM-DD for the engine's week-start date"
                )
        return label
    if grain == "month" and _MONTH.fullmatch(label):
        return label
    if grain == "quarter" and _QUARTER.fullmatch(label):
        return label
    if grain == "year" and _YEAR.fullmatch(label) and int(label) > 0:
        return label
    formats = {
        "month": "YYYY-MM",
        "quarter": "YYYYQn",
        "year": "YYYY",
    }
    raise ValueError(f"{grain.title()} periods must use {formats[grain]}")

