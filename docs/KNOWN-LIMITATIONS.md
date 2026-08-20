# Known Limitations

Deliberately accepted gaps in the current system. Each entry states what the
limitation is, why it was accepted rather than fixed, and what would be
required to close it. These are scoping decisions, not defects to be silently
patched as a side effect of unrelated work.

## Percentage, rate, and ratio columns are classified as additive quantities

`app.services.tabular.classify_numeric_role()` assigns every numeric column one
of `identifier`, `cyclical`, `discrete_scale`, or `quantity`, and only
`quantity` is offered as a summable KPI in the investigation wizard.

A numeric column representing a percentage, rate, or ratio (`discount_pct`,
`margin_pct`, `conversion_rate`) is classified as `quantity` and therefore
remains selectable as an additive KPI, even though summing such a column across
rows is not meaningful — the correct treatment is a weighted average or a
ratio of sums.

The three signals that catch the other non-additive cases cannot catch this
one. `identifier` and `discrete_scale` are both cardinality-driven, and a
continuous percentage column has cardinality indistinguishable from a genuine
business quantity; `cyclical` is bounded by calendar-unit name tokens that a
rate column does not match. No threshold applied to the existing signals
separates a rate from a quantity.

Closing this would require a name-token heuristic (`pct`, `percent`, `rate`,
`ratio`, `margin`) analogous to `DATE_NAME_TOKENS`. That was deliberately
deferred: it is a lower-confidence signal than the cardinality and calendar
checks, it carries real false-positive risk against legitimately additive
columns, and it deserves its own deliberate scoping rather than inclusion by
default because it surfaced during an unrelated diagnostic.
