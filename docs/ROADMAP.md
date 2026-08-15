# Production Roadmap

## Current evidence-based assessment

The current portfolio product is the AI Root Cause Investigation Agent. RCA V1 runs through a stable FastAPI contract and a focused Next.js investigation workspace. Its governed production path maintains typed investigation state, calculates signed contributions deterministically, handles offsets and reconciliation, applies scoped data-quality gates, tests competing explanations, verifies evidence, and compiles non-causal conclusions.

The production path has completed a real full-stack browser smoke test and five controlled robustness scenarios: a clear driver, competing explanations, data-quality abstention, no material driver, and a non-revenue operations case. These fixtures provide bounded regression evidence, not a universal accuracy claim. Immediate work should prioritize broader evaluated evidence and public-production boundaries rather than expanding into a generic analytics assistant.

## Phase 0 — Correct the product boundary — Complete

- Replace client-supplied filesystem paths with validated dataset uploads and internal dataset IDs.
- Create structured domain contracts and enforce evidence traceability.
- Turn Ask into a real analysis brief with stakeholder and decision context.
- Add migration tooling and a clean local development setup.

Exit criteria: a safe CSV/XLSX upload starts a run without exposing a filesystem path, and invalid claim links fail validation.

## Phase 1 — Dataset-aware analytical core — Core complete

- Build generic profiling with semantic-type inference, nulls, duplicates, cardinality, ranges, dates, distributions, and PII warnings.
- Generate a typed analysis plan from the confirmed brief and profile.
- Execute only allow-listed operations; do not execute model-authored Python or SQL.
- Store immutable dataset versions and transformation manifests per run.
- Build evidence records from operation outputs.
- Expand supported operations with contribution, cohort, funnel, anomaly, and statistical-test modules as validated use cases require them.

Exit criteria: at least five distinct fixture datasets and question types complete without dataset-specific branches.

## Phase 2 — Durable workflow and artifacts

- Replace `MemorySaver` with the PostgreSQL LangGraph checkpointer.
- Move uploads, cleaned datasets, charts, and reports to private S3-compatible object storage.
- Run analyses through a background worker and stream progress to the UI.
- Make every node idempotent and safe to retry.

Exit criteria: a server restart during a checkpoint or long analysis does not lose the run.

## Phase 3 — Trust, security, and observability

- Add authentication, workspaces, role-based access, row-level authorization, and signed artifact URLs.
- Add upload malware/type checks, spreadsheet-formula protection, retention policies, and privacy classification.
- Add structured logs, traces, prompt/model versions, token/cost tracking, latency, and error taxonomy.
- Add request limits, quotas, circuit breakers, and provider fallbacks.

Exit criteria: cross-workspace access tests fail closed; every model call and analytical claim is traceable.

## Phase 4 — Evaluation and release discipline

- Convert manual scripts to isolated unit and integration tests.
- Create golden datasets/questions with expected plans, calculations, evidence links, and refusal behavior.
- Add data-quality, question-coverage, hallucination, chart-integrity, and recommendation-grounding evaluations.
- Run lint, types, tests, migrations, frontend build, and evaluation thresholds in CI.

Exit criteria: prompt, model, and code changes cannot merge when correctness or grounding regresses.

## Phase 5 — Professional workspace UX

- Add analysis history, dataset catalog, run comparison, and resumable checkpoints.
- Present a decision-ready report: answer, evidence, charts, methodology, limitations, and actions.
- Add evidence drill-down and transformation lineage instead of raw pipeline logs.
- Support export to HTML/PDF and governed sharing.

Exit criteria: a non-technical user can understand what the system concluded, why, and what remains uncertain without seeing internal file paths or implementation logs.

## Immediate build order

1. Durable PostgreSQL checkpointer and object storage.
2. Authentication and workspace isolation.
3. Background jobs and progress streaming.
4. Observability, model/cost logging, and prompt versioning.
5. Broader golden-dataset evaluation suite and CI.
6. Additional analytical operations driven by evaluated use cases.
