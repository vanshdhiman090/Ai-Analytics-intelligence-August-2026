"""The one placeholder-label vocabulary shared by profiling and verification.

A "placeholder" segment label is a value that carries no business meaning --
it is how a source system spells "we did not record this". Such a label can
still be the arithmetically largest contributor to a KPI movement, which is
a real and useful measurement, but it names no interpretable business
population, so it cannot support a descriptive explanation of *what changed*.

This vocabulary is deliberately conservative. A false positive suppresses a
valid explanation, which is worse than missing one, so ambiguous words that
are legitimate business categories in real datasets are excluded -- most
notably "other", which is a genuine catch-all segment in many taxonomies.
"""

from __future__ import annotations

# Matched case-insensitively against the stripped label. Includes the empty
# string and the investigation engine's own missing-value sentinels
# (root_cause._normalized_dimension_values writes "__MISSING__"; the
# driver/segment projections write "<missing>"), so a label that only became
# a placeholder through normalization is caught by the same check.
PLACEHOLDER_SEGMENT_LABELS: frozenset[str] = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "none",
        "not defined",
        "null",
        "tbd",
        "unknown",
        "unspecified",
        "__missing__",
        "<missing>",
    }
)


def is_placeholder_segment_label(value: object) -> bool:
    """True when a segment label is a missing-data placeholder, not a business category."""
    if value is None:
        return True
    return str(value).strip().lower() in PLACEHOLDER_SEGMENT_LABELS
