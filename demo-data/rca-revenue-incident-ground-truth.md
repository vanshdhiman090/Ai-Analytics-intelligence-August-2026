# RCA revenue incident — ground truth

This fixture is a deterministic, order-level ecommerce benchmark for the V1 Root Cause Investigation product. It contains one unique order per row and represents two complete monthly periods. Every calendar date in January and February 2026 appears in the dataset.

## KPI definition

- KPI: Revenue
- Metric column: `revenue`
- Aggregation: `sum`
- Time column: `date`
- Grain: `month`
- Unit: EUR
- Baseline period: `2026-01`
- Comparison period: `2026-02`

## Expected incident

| Measure | Expected value |
| --- | ---: |
| January revenue | €16,000 |
| February revenue | €14,600 |
| Signed movement | -€1,400 |
| Percentage movement | -8.75% |

## Expected investigation path

1. `country = Germany`: €4,000 → €2,800, a **-€1,200** contribution, or **85.71%** of the global -€1,400 movement.
2. Within Germany, `device = Mobile`: €2,000 → €900, a **-€1,100** contribution, or **91.67%** of Germany's -€1,200 movement.
3. Within Germany → Mobile, `customer_type = Returning`: €1,500 → €100, a **-€1,400** contribution, or **127.27%** of the Germany → Mobile -€1,100 movement.

The expected selected descriptive path is:

`Germany → Mobile → Returning`

## Signed offsets and reconciliation

### Country decomposition at the global scope

- Germany: -€1,200
- France: +€200 positive offset
- United Kingdom: -€300
- United States: -€100

Reconciliation:

`-€1,200 + €200 - €300 - €100 = -€1,400`

Total downward pressure is -€1,600, positive offsets are +€200, and net movement is -€1,400.

### Device decomposition within Germany

- Mobile: -€1,100
- Desktop: -€100

Reconciliation:

`-€1,100 - €100 = -€1,200`

### Customer-type decomposition within Germany → Mobile

- Returning: -€1,400
- New: +€300 positive offset

Reconciliation:

`-€1,400 + €300 = -€1,100`

Returning contributes **127.27%** of the parent movement because the +€300 New-customer offset reduces the final net decline. Percentages above 100% are valid signed contribution arithmetic and must not be clamped.

Every approved dimension is a mutually exclusive partition of the same scoped order rows, so every dimension test must reconcile to its parent movement with a zero residual.

## Data-quality expectations

- 320 rows total: 160 January orders and 160 February orders.
- Every date from 2026-01-01 through 2026-01-31 is represented.
- Every date from 2026-02-01 through 2026-02-28 is represented.
- Overall and scoped comparison row coverage is `1.0`, above the server-owned `0.80` minimum.
- Rows per period are safely above the five-row drill-down minimum:
  - Germany: 40 baseline / 40 comparison
  - Germany → Mobile: 20 baseline / 20 comparison
  - Germany → Mobile → Returning: 10 baseline / 10 comparison
- Required fields are populated, order IDs are unique, dates are valid, and revenue has no nulls.
- Row ordering is not part of the answer; deterministic verification must return the same path after shuffling.

## Epistemic boundary

This is descriptive contribution ground truth, not causal ground truth. The fixture proves which tested segments mathematically account for the observed revenue movement. It does not prove why customer behavior changed or that being in Germany, using Mobile, or being a Returning customer caused the decline.
