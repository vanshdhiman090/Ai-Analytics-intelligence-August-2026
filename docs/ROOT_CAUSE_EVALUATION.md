# Controlled Root Cause Evaluation Suite

## Purpose

This suite measures whether a structured Root Cause Analytics answer is correct. It is separate from backend unit tests, browser tests, and the production `RootCauseAgent` implementation.

The benchmark contains ten synthetic incidents with known answers:

1. Germany mobile payment failures
2. Product stock-out
3. Traffic-quality decline
4. Discount mix reducing average order value
5. Missing ingestion rows
6. Seasonal weekend decline
7. Promotion ending with experimental evidence
8. Mixed-driver revenue incident
9. False anomaly
10. Insufficient evidence

The cases cover business incidents, data incidents, normal variation, mixed drivers, and mandatory abstention.

## Scorecard

The suite publishes these independent metric names:

- `anomaly_detection`
- `incident_classification`
- `primary_branch`
- `affected_segment`
- `contribution_accuracy`
- `hypothesis_status_accuracy`
- `correct_abstention`
- `explained_impact_reconciliation`
- `causal_claim_safety`
- `evidence_traceability`

Case severity weights are `critical=5`, `high=3`, `medium=2`, and `low=1`. The overall score is a weighted average of the scorecard metrics. The release baseline is intentionally fail-closed for incident classification, abstention, reconciliation, causal safety, evidence traceability, and every critical incident.

## Files

- `backend/evals/root_cause_cases.json`: incident descriptions and answer keys
- `backend/evals/root_cause_reference_predictions.json`: known-good scorer calibration fixture
- `backend/evals/root_cause_baseline.json`: release thresholds
- `backend/app/evals/root_cause_runner.py`: independent scorer, report writer, and integration hook
- `backend/tests/test_root_cause_evaluations.py`: scorer regression tests

The reference predictions prove that the scorer and answer keys agree. They are **not** evidence that the production agent scored 100%. A real agent score is valid only after exporting the agent's structured predictions and passing that file with `--predictions`.

## Prediction contract

Each prediction is keyed by `case_id` and contains:

```json
{
  "case_id": "RCA-001",
  "is_anomaly": true,
  "incident_type": "business_incident",
  "primary_branches": ["conversion"],
  "affected_segments": [{"country": "Germany", "device": "mobile"}],
  "contributions": [
    {"driver_id": "germany_mobile_payment_failures", "absolute_impact": -6000, "evidence_ids": ["E1"]}
  ],
  "hypotheses": [
    {"hypothesis_id": "payment_failure", "status": "supported", "statement": "...", "evidence_ids": ["E2"]}
  ],
  "abstained": false,
  "reconciliation": {
    "total_movement": -10000,
    "explained_movement": -8000,
    "unexplained_movement": -2000
  },
  "evidence": [{"evidence_id": "E1"}, {"evidence_id": "E2"}],
  "findings": [{"finding_id": "F1", "statement": "...", "evidence_ids": ["E1", "E2"]}],
  "conclusion": "..."
}
```

Allowed hypothesis statuses are `supported`, `partially_supported`, `rejected`, and `unresolved`. Allowed incident types are `business_incident`, `data_incident`, `normal_variation`, and `insufficient_evidence`.

## Run

From `backend`:

```powershell
python -m app.evals.root_cause_runner --predictions evals/root_cause_reference_predictions.json
```

Run only the RCA evaluator tests:

```powershell
python -m pytest tests/test_root_cause_evaluations.py -q
```

Reports are written to `backend/evals/reports/root-cause/latest.json` and `latest.html`. The reports directory is already ignored by Git.

## Integration hook

`combine_with_analytical_release(analytical_summary, root_cause_summary)` combines the existing deterministic analytical gate with the RCA gate. It preserves the existing `category_scores` object, so legacy tests and API consumers retain the original category names. RCA metric names are nested under `root_cause_gate.metric_scores`.

The hook is intentionally explicit rather than automatically modifying the existing evaluation API. Product code can adopt the combined release decision when production `RootCauseAgent` outputs conform to the prediction contract.

## Interpretation

- A scorer-calibration result answers: “Can the benchmark detect known correct and incorrect outputs?”
- A production-agent result answers: “Did this agent identify the known incident correctly?”
- Passing backend unit tests does not imply passing this analytical benchmark.
- A failed causal-safety or evidence-traceability metric blocks release even if the numerical contribution is correct.
