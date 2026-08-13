# Real RCA smoke test

Use this short guide to test the real frontend and backend together. You do not need to call an API manually.

## 1. Start the application

1. Open PowerShell in the repository root.
2. Run:

   ```powershell
   .\Start-Agent.cmd
   ```

3. Wait until the startup window reports that the application is ready.

## 2. Open the RCA workspace

Open [http://127.0.0.1:3010](http://127.0.0.1:3010) in your browser.

## 3. Upload the benchmark

Upload:

`demo-data/rca-revenue-incident.csv`

Confirm that the dataset preview shows these columns:

`date`, `order_id`, `revenue`, `country`, `device`, `customer_type`, `acquisition_channel`

## 4. Configure the investigation

Enter exactly:

| Field | Value |
| --- | --- |
| KPI name | Revenue |
| Metric | revenue |
| Time | date |
| Grain | month |
| Unit | EUR |
| Baseline | 2026-01 |
| Comparison | 2026-02 |
| Candidate dimensions | country, device, customer_type, acquisition_channel |

## 5. Run and check the result

Start the investigation. The investigation path should be:

`Germany → Mobile → Returning`

Also check:

- KPI movement: €16,000 → €14,600, signed change -€1,400 (-8.75%).
- Leading tested contributor: Returning within Germany → Mobile, -€1,400.
- Contribution share: 127.27% of the Germany → Mobile movement.
- Positive offset: New customers within Germany → Mobile, +€300.
- Reconciliation: residual €0; the selected decomposition reconciles.
- Readiness: ready with caveats.
- Robustness: not verified at the selected target.
- Data quality: pass.
- Caveats: material offsets, maximum-depth boundary, and robustness applying only upstream.
- Recommended next action: increase investigation depth.

These are descriptive contribution results, not a confirmed causal root cause.

## 6. Record any problem

If anything differs, take a screenshot and record:

- the step where it failed;
- the exact error message;
- the values or path shown;
- whether the frontend loaded;
- whether upload completed;
- whether the investigation request completed.

Only use manual API calls if the browser workflow itself fails.
