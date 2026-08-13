"""One governed period-comparison context shared by analysis and RCA."""

from __future__ import annotations

import re
from typing import Mapping, Literal

from pydantic import BaseModel, ConfigDict, Field


_MONTH_NAMES = "January February March April May June July August September October November December".split()
_MONTH_LOOKUP = {
    **{name.lower(): index for index, name in enumerate(_MONTH_NAMES, start=1)},
    **{name[:3].lower(): index for index, name in enumerate(_MONTH_NAMES, start=1)},
}


class ComparisonContext(BaseModel):
    """Typed, immutable meaning of a user-requested period comparison."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    baseline_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    comparison_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    period_granularity: Literal["month"] = "month"
    period_source: Literal["explicit_user_request"] = "explicit_user_request"
    metric: str | None = None


def extract_explicit_comparison_context(state: Mapping[str, object]) -> ComparisonContext | None:
    """Extract exactly two named months from user-facing request text, never infer one."""
    supplied = state.get("comparison_context")
    if supplied:
        return ComparisonContext.model_validate(supplied)
    if state.get("baseline_period") and state.get("comparison_period"):
        return ComparisonContext(
            baseline_period=str(state["baseline_period"]),
            comparison_period=str(state["comparison_period"]),
        )
    text = " ".join(str(state.get(key) or "") for key in ("business_question", "rough_prompt", "confirmed_question"))
    iso = re.findall(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", text)
    if len(iso) >= 2:
        return ComparisonContext(
            baseline_period=f"{iso[0][0]}-{int(iso[0][1]):02d}",
            comparison_period=f"{iso[1][0]}-{int(iso[1][1]):02d}",
        )
    month_pattern = "|".join(_MONTH_NAMES + [name[:3] for name in _MONTH_NAMES])
    matches = re.findall(rf"\b({month_pattern})\.?\s+(20\d{{2}})\b", text, flags=re.IGNORECASE)
    if len(matches) < 2:
        return None
    first, second = matches[0], matches[1]
    # "October compared with September" describes October as the comparison
    # value and September as its baseline; the grammatical order is reversed.
    between = text.lower().split(f"{first[0]} {first[1]}".lower(), 1)
    if len(between) == 2 and "compared with" in between[1].split(f"{second[0]} {second[1]}".lower(), 1)[0]:
        first, second = second, first
    return ComparisonContext(
        baseline_period=f"{first[1]}-{_MONTH_LOOKUP[first[0].lower()]:02d}",
        comparison_period=f"{second[1]}-{_MONTH_LOOKUP[second[0].lower()]:02d}",
    )
