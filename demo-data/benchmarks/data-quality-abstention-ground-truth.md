# Data-quality abstention — ground truth

## Scenario

This order-level ecommerce fixture simulates a partially loaded February partition. January contains five records per leaf segment, while February contains only two.

## Expected arithmetic and quality gate

- January rows: 160
- February rows: 64
- Comparison row coverage: `64 / 160 = 0.40`
- Current server minimum: `0.80`
- January recorded revenue: €16,000
- February recorded revenue: €6,400

The observed -€9,600 movement must not be interpreted as a business decline because the comparison-period row coverage fails the governed completeness gate.

## Expected public result

- Claim: `data_quality_abstention`
- Terminal status: `blocked_by_data_quality`
- Readiness: `not_ready / data_quality`
- Robustness: `abstained`
- Data quality: `blocked`
- Issue: `comparison_coverage_incomplete`
- `affects_selected_target = true`
- No selected contribution path

The API should return a successful analytical response containing the abstention, not fabricate a driver.
