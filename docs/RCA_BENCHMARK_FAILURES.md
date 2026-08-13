# RCA Benchmark Failure #1 — Incorrect Date Semantic Inference

## Incident

The Nike benchmark uses `Invoice Date` values in `DD-MM-YYYY` format. The old
profile used pandas' default parser, which only parsed a minority of the
column. Later analysis paths used independent mixed-format parsing, allowing
the same source values to be interpreted month-first. This produced incorrect
monthly totals and therefore an incorrect RCA incident.

## Corrected contract

`app.services.tabular.infer_date_semantics()` now evaluates the entire column
against explicit safe formats: ISO, day-first dash/slash, month-first
dash/slash, and ISO-8601 timestamps. It records one of:

- `CONFIDENT_DATE_FORMAT` — exactly one column-wide interpretation, or
  equivalent interpretations, meets the 99% parse threshold.
- `AMBIGUOUS_DATE_FORMAT` — more than one non-equivalent interpretation fits;
  analysis stops rather than guessing.
- `INVALID_DATE_COLUMN` — no complete supported interpretation fits; analysis
  stops rather than dropping or reinterpreting records.

The raw source column is retained. The profile and processing audit record the
detected format, confidence/status, parsed/failed counts, min/max dates, and
missing monthly periods. The normalized datetime series exists in memory only.

## Shared downstream rule

Trend, period comparison, segment-change analysis, the RCA engine, and the
portable project-file reproduction all use this strict column-wide rule. They
cannot silently fall back to pandas mixed parsing.

## Verified Nike regression

Using the normal cleaned-data → allow-listed analysis → RCA path:

| Period | Total Sales |
| --- | ---: |
| August 2021 | 681,562 |
| September 2021 | 564,937 |

The September-versus-August change is **−116,625 (−17.11%)**. This is an
observed movement and a valid mathematical RCA input; it is not, by itself, a
causal conclusion.

## Governed learning

This incident is eligible to be recorded as a candidate learning-memory lesson
only after the recovery is validated by the regression and production workflow.
Candidate lessons never bypass schema checks, date parsing, evidence gates, or
causal-language review; only the existing governed promotion lifecycle may make
a recovered lesson available to a later specialist.

# RCA Benchmark Failure #2 — Explicit Period Context Not Propagated Consistently

## Symptom

One analysis section could use the user-requested September 2021 to October
2021 comparison while a segment decomposition or RCA report reverted to the
latest available months. This could reverse the incident direction or make a
report contradict its own evidence register.

## Root technical cause and fix

Period selection was previously local to each operation: `segment_change`
selected the latest two observed periods, while RCA separately extracted named
periods from the question. A typed `ComparisonContext` is now created once from
an explicit user request and propagated into the approved time operations, the
evidence diagnostics, RCA, charts, and publication state. An explicit pair has
precedence; automatic latest-period selection remains only when no context
exists. All changes use `comparison - baseline`.

## Regression protection and validated recovery

Tests cover explicit propagation, direction, Product/Retailer/Sales Method/
Region decomposition metadata, RCA orientation, reviewer rejection of a
mismatch, and automatic fallback without explicit months. The full backend
suite passed after the change.
