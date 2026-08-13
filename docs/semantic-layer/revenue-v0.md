# Revenue Semantic Layer V0

## Canonical contract

- **Metric:** Revenue
- **Definition:** `SUM(net_revenue)`
- **Grain:** one order per row
- **Included orders:** completed
- **Excluded orders:** cancelled
- **Refund treatment:** `net_revenue` is already post-refund; refunds must not be subtracted twice
- **Currency:** one explicit reporting currency, either native single-currency data or values converted before aggregation
- **Timezone:** an explicit IANA timezone controls period boundaries
- **Default baseline:** previous comparable period; alternative baselines must come from the allow-list

The runtime contract is implemented in `backend/app/domain/revenue_semantics.py`. It is strict and JSON serializable so it can later be attached to a session without database changes.

Field bindings can be inferred from the existing schema profile using a small, explicit alias registry. Inference abstains if a required field is missing, has an incompatible semantic type, appears in more than one matching column, or would mix order-grain fields across sources. It never uses fuzzy matching. Optional ambiguous fields are withheld so their driver branches remain unavailable.

## Measurable driver tree

Only exact branches supported by bound, available columns are returned:

1. `revenue = order_count × average_order_value`
2. `net_revenue = gross_revenue - discount_amount - refund_amount`
3. `order_count = session_count × conversion_rate`

Unavailable branches remain visible with their missing bindings. A branch is not invented from similarly named columns.

## Current execution boundary

The generic analysis executor supports sums, ratios, period comparisons, and segment changes, but its operation contract does not yet express semantic filters or distinct counts. The Revenue layer therefore publishes the deterministic capabilities each branch requires and does not silently translate the contract into an unsafe generic plan. A later integration should add filtered aggregation and distinct-count operations, then pass the resolved semantic contract into the approved analysis plan.

## Source inventory

| Source checked | Confidence | Use |
| --- | --- | --- |
| Master project prompt | High | Canonical Revenue definition, driver-tree policy, safety requirements |
| `backend/app/domain/contracts.py` | High | Existing typed analysis operations and evidence contracts |
| `backend/app/services/analysis.py` | High | Current deterministic executor capabilities and gaps |
| `backend/app/services/tabular.py` | High | Existing inferred physical semantic types |
| `backend/app/api/routers/sessions.py` | High | JSON session envelope and API persistence boundary |

## Known caveat

V0 defines and validates Revenue semantics; it does not yet change orchestration or execute the driver decomposition. That separation prevents the existing workflow from claiming semantic compliance before filtered and distinct-count operations are implemented and evaluated.
