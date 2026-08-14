# Operations late-units incident — ground truth

## Scenario

This shipment-level operations fixture investigates an increase in the additive KPI `late_units`. It intentionally uses no ecommerce revenue vocabulary.

## Expected incident

- January late units: 1,600
- February late units: 1,740
- Signed movement: +140 (+8.75%)

## Expected path and reconciliation

1. Region = Europe: +120, or 85.71% of the global +140 movement.
2. Within Europe, Carrier = Carrier B: +110, or 91.67% of Europe's +120 movement.
3. Within Europe → Carrier B, Warehouse = Warehouse North: +140, or 127.27% of Carrier B's +110 movement.

Expected path:

`Europe → Carrier B → Warehouse North`

Global region reconciliation:

`Europe +120 + Asia +30 + Latin America +10 + North America -20 = +140`

Within Europe:

`Carrier B +110 + Carrier A +10 = +120`

Within Europe → Carrier B:

`Warehouse North +140 + Warehouse South -30 = +110`

Warehouse South is a -30 opposing offset. Consequently, Warehouse North contributes 127.27% of its parent movement; this valid signed percentage must not be clamped.

## Expected public result

- Claim: `leading_tested_contributor`
- Terminal status: `bounded_by_max_depth`
- Readiness: `ready_with_caveats`
- Selected-target robustness: `not_verified`
- Data quality: `pass`
- Selected decomposition residual: 0 units

The result is a descriptive contribution path, not a causal statement about carriers or warehouses.
