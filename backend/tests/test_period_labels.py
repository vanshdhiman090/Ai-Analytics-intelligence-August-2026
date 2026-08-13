import pandas as pd
import pytest

from app.services.period_labels import format_period_values, validate_period_label


@pytest.mark.parametrize(
    ("grain", "label"),
    [
        ("day", "2026-08-13"),
        ("week", "2026-08-10"),
        ("month", "2026-08"),
        ("quarter", "2026Q3"),
        ("year", "2026"),
    ],
)
def test_canonical_period_labels(grain, label):
    assert validate_period_label(label, grain) == label


@pytest.mark.parametrize(
    ("grain", "label"),
    [
        ("day", "2026-02-30"),
        ("week", "2026-08-11"),
        ("month", "2026-13"),
        ("quarter", "2026Q5"),
        ("year", "26"),
    ],
)
def test_invalid_period_labels_fail_closed(grain, label):
    with pytest.raises(ValueError):
        validate_period_label(label, grain)


def test_formatter_preserves_engine_period_semantics():
    values = pd.Series(pd.to_datetime(["2026-08-13"]))

    assert format_period_values(values, "day").iloc[0] == "2026-08-13"
    assert format_period_values(values, "week").iloc[0] == "2026-08-10"
    assert format_period_values(values, "month").iloc[0] == "2026-08"
    assert format_period_values(values, "quarter").iloc[0] == "2026Q3"
    assert format_period_values(values, "year").iloc[0] == "2026"

