# Hero demo: investigating a revenue decline

This walkthrough uses the real V1 RCA product path and the deterministic fixture [`demo-data/rca-revenue-incident.csv`](../demo-data/rca-revenue-incident.csv). It is a recruiter-facing explanation of a verified descriptive investigation, not a causal case study.

## 1. Business incident

An ecommerce team observes that monthly Revenue declined from **€16,000 in January 2026** to **€14,600 in February 2026**.

```text
Signed movement: -€1,400
Percentage movement: -8.75%
```

The product question is bounded: which tested segments mathematically contributed most to this movement, how safely does the evidence support that description, and what should an analyst test next?

## 2. Dataset

The fixture contains 320 unique order-level rows and seven fields:

`date`, `order_id`, `revenue`, `country`, `device`, `customer_type`, `acquisition_channel`

It includes 160 January orders and 160 February orders. Both monthly periods have complete calendar-date representation.

## 3. Investigation request

```text
KPI: Revenue
Aggregation: SUM(revenue)
Time field and grain: date / month
Unit: EUR
Baseline: 2026-01
Comparison: 2026-02
Approved dimensions: country, device, customer_type, acquisition_channel
```

The client does not control depth, materiality, coverage, reconciliation, verification, or conclusion thresholds.

## 4. Data-quality gate

Before ranking contributors, the runtime verifies required columns, unambiguous dates, presence of both periods, comparison coverage, and KPI completeness.

For this fixture:

- both requested periods are present;
- comparison row coverage is `160 / 160 = 1.0`, above the governed `0.80` minimum;
- the revenue metric has no nulls;
- every recursive scope has enough baseline and comparison rows;
- the result passes the data-quality gate.

If these checks failed, the engine would return a data-quality incident or abstention instead of interpreting the recorded decline as business truth.

## 5. Investigation path

The verified selected path is:

```text
Global
  ↓ country
Germany: -€1,200 (85.71% of global -€1,400)
  ↓ device within Germany
Mobile: -€1,100 (91.67% of Germany -€1,200)
  ↓ customer_type within Germany → Mobile
Returning: -€1,400 (127.27% of Mobile -€1,100)
```

At every scope, the engine tests the remaining approved dimensions, records evidence, updates bounded hypothesis status, and selects the next defensible segment. It stops after depth three because the public V1 policy owns that boundary.

## 6. Contribution arithmetic

### Country at the global scope

```text
Germany          -€1,200
France             +€200  positive offset
United Kingdom     -€300
United States      -€100
                  -------
Net movement     -€1,400
```

Total downward pressure is -€1,600. The France offset reduces the observed net decline to -€1,400.

### Device within Germany

```text
Mobile           -€1,100
Desktop            -€100
                  -------
Germany total    -€1,200
```

### Customer type within Germany → Mobile

```text
Returning        -€1,400
New                +€300  positive offset
                  -------
Mobile total     -€1,100
```

Returning contributes **127.27%** of its parent movement because an opposing +€300 contribution reduces the final parent decline. Percentages above 100% are valid signed arithmetic when offsets exist; the UI does not clamp them.

Every tested dimension is a mutually exclusive partition of the relevant order rows, so each decomposition reconciles to its parent with zero tie-out residual.

## 7. Competing and offset evidence

The investigation does not hide evidence that complicates the leading path:

- France offsets the global decline by +€200.
- New customers offset the Germany → Mobile decline by +€300.
- Other countries contribute an additional -€400 of downward movement.
- Desktop contributes -€100 within Germany.

This distinction between downward pressure, positive offsets, net movement, and remaining segment movement prevents a simplistic “largest percentage wins” conclusion.

## 8. Conclusion

The selected public claim is a **leading tested contributor**:

> Returning customers within Germany → Mobile contributed -€1,400 to the tested Revenue movement.

The result is `ready_with_caveats` for a stronger descriptive explanation. The terminal state is `bounded_by_max_depth`.

Robustness is **not verified at the selected target**. Any verification that applies only to an upstream scope is not visually or semantically attached to the deepest target.

## 9. Caveats

- Material positive offsets affect the net movement.
- The investigation reached the server-governed maximum depth of three.
- Robustness does not apply to the deepest selected target.
- Only the approved dimensions were tested.
- A mathematical contribution path is not a behavioral or causal mechanism.

## 10. Recommended next action

Further drill-down may be analytically useful, but this investigation has reached the current server-governed depth limit. A human analyst should identify a specific, business-relevant next dimension or collect mechanism-level evidence rather than treating the current path as causal proof.

## 11. Why this is not causal proof

The data establishes that the selected segments account for signed changes in the additive Revenue decomposition. It does not establish why Returning customers changed behavior or whether country, device, or customer type caused the decline.

A causal claim would require a suitable design and evidence—for example a randomized intervention, a credible natural experiment, or a controlled causal model with justified assumptions. Those capabilities are outside RCA V1.

## 12. Engineering components executed

```text
Browser investigation workspace
  → POST /datasets
  → dataset validation and deterministic profiling
  → POST /v1/rca/investigations
  → governed dataset resolver/loader
  → public request mapped to a typed investigation request
  → hypothesis planner and bounded controller
  → deterministic scoped contribution tests
  → falsification and verification
  → deterministic conclusion compiler
  → sanitized public response with response-local evidence references
  → frontend investigation path, decomposition, caveats, and next action
```

The language model is not trusted with arithmetic. Provider proposals must pass strict validation, and unavailable or rejected proposals use deterministic fallback. No model-written Python or SQL is executed.

## Reproduce it

Follow [`demo-data/REAL_RCA_SMOKE_TEST.md`](../demo-data/REAL_RCA_SMOKE_TEST.md). The exact arithmetic and expected quality conditions are recorded in [`demo-data/rca-revenue-incident-ground-truth.md`](../demo-data/rca-revenue-incident-ground-truth.md).
