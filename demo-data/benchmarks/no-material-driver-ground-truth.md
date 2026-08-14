# No material driver — ground truth

## Scenario

This order-level ecommerce fixture distributes a real revenue decline evenly across six distinct segments in every approved dimension.

## Expected arithmetic

- January revenue: €3,600
- February revenue: €3,540
- Signed movement: -€60 (-1.67%)
- Each of the six segment groups contributes exactly -€10.
- Each segment therefore contributes `10 / 60 = 16.67%` of the net movement.
- Every dimension reconciles: `6 × -€10 = -€60`.

The current material-leader threshold is 20%, so no tested segment qualifies. Changing the threshold to make this case produce a leader would invalidate the benchmark.

## Expected public result

- Claim: `inconclusive`
- Terminal status: `no_material_driver`
- Readiness: `not_ready / insufficient_evidence`
- Robustness: `not_verified`
- Data quality: `pass`
- No selected contribution path

This is a diffuse descriptive movement, not evidence that no real-world mechanism exists.
