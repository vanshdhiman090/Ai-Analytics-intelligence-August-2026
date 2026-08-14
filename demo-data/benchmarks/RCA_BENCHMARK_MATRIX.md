# RCA real-world robustness benchmark matrix

All actual results below come from the public V1 service mapping under deterministic provider-fallback execution. Claims are descriptive, never causal.

| Scenario | Domain | KPI | Baseline → comparison | Intended challenge | Expected claim | Expected terminal state | Expected path | Expected DQ | Expected robustness | Key arithmetic | Actual result | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A. Clear ecommerce driver | Ecommerce | Revenue | €16,000 → €14,600 | Control case with signed offset and depth boundary | `leading_tested_contributor` | `bounded_by_max_depth` | Germany → Mobile → Returning | Pass | Not verified at deepest target | -€1,400 net; Returning -€1,400 plus New +€300 = Mobile -€1,100 | Claim, path, readiness, DQ, robustness, and €0 residual matched | PASS |
| B. Competing explanations | Ecommerce | Revenue | €16,000 → €14,800 | Country leader versus near-equal device decomposition | `competing_explanations` | `inconclusive` | Germany → Mobile | Pass | Not verified at deeper selected target; root competition remains explicit in claim | Germany -€1,000; Mobile -€900; runner-up ratio 0.90 ≥ 0.80 | Competing claim returned; no unique explanation presented; €0 residual | PASS |
| C. Data-quality abstention | Ecommerce | Revenue | €16,000 → €6,400 recorded | February partition only 40% as complete by row coverage | `data_quality_abstention` | `blocked_by_data_quality` | None | Blocked | Abstained | 64 / 160 = 0.40 coverage, below 0.80 | Blocking `comparison_coverage_incomplete` affects selected target; no driver returned | PASS |
| D. No material driver | Ecommerce | Revenue | €3,600 → €3,540 | Diffuse movement across six segments | `inconclusive` | `no_material_driver` | None | Pass | Not verified | Six × -€10 = -€60; each share 16.67% < 20% | No leader selected; threshold unchanged | PASS |
| E. Operations late units | Supply-chain operations | Late shipment units | 1,600 → 1,740 units | Non-revenue domain, recursive path, opposing offset | `leading_tested_contributor` | `bounded_by_max_depth` | Europe → Carrier B → Warehouse North | Pass | Not verified at deepest target | +140 net; Warehouse North +140 plus Warehouse South -30 = Carrier B +110 | Claim, path, readiness, DQ, robustness, and zero residual matched | PASS |

## Policy interpretation notes

- `robust_descriptive_explanation` is reachable when bounded verification completes and applies to the selected target without a material contradiction.
- `competing_explanations` is triggered when the strongest alternative tested decomposition is at least 0.80 of the provisional leader's magnitude.
- `data_quality_abstention` requires a blocking failure at the exact conclusion scope.
- `no_material_driver` is returned when a real movement exists but no tested aligned segment meets the 20% materiality and evidence-strength gates.
- `blocked_by_reconciliation` requires completed tests whose additive partitions do not reconcile. These fixtures use mutually exclusive complete dimensions, so this is intentionally not triggered.
- `incomplete_testing` is reachable when required dimensions are not completed or requested verification is unfinished. The production controller tests every eligible dimension in these fixtures, so this is intentionally not triggered.
- Public RCA V1 sets a maximum depth of 3. Depth-bounded path cases therefore return `bounded_by_max_depth` even when their descriptive arithmetic is ready with caveats.
