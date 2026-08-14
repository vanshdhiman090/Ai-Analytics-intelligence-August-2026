# Competing explanations — ground truth

## Scenario

This order-level ecommerce fixture compares January 2026 with February 2026 for additive revenue. The approved dimensions are `country` and `device`.

## Expected arithmetic

- January revenue: €16,000
- February revenue: €14,800
- Signed movement: -€1,200 (-7.5%)
- Country decomposition:
  - Germany: -€1,000
  - France: +€100 offset
  - United Kingdom: -€200
  - United States: -€100
  - Reconciliation: `-1,000 + 100 - 200 - 100 = -1,200`
- Device decomposition:
  - Mobile: -€900
  - Desktop: -€300
  - Reconciliation: `-900 - 300 = -1,200`

Germany is the provisional mathematical leader. Mobile is a different tested decomposition with `900 / 1,000 = 0.90` of the leader's magnitude, above the current material-competing-driver ratio of 0.80.

Within Germany, Mobile contributes -€800, or 80% of Germany's -€1,000 movement. The selected path is therefore `Germany → Mobile`, while the bounded conclusion must still report competing explanations rather than uniqueness.

## Expected public result

- Claim: `competing_explanations`
- Terminal status: `inconclusive`
- Readiness: `not_ready / competing_explanations`
- Data quality: `pass`
- Selected-target robustness: `not_verified`, because the competing-driver verification applies to the upstream root selection rather than the deeper selected target
- Selected decomposition residual: €0

This benchmark tests descriptive competition between decompositions. It does not establish either dimension as causal.
