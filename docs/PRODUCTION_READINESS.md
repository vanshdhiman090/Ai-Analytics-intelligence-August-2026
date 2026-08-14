# Production readiness

## Implemented

- Durable LangGraph checkpoints in PostgreSQL, including restart-safe human approvals.
- Asynchronous API execution with bounded workers, retry, explicit run states, and persisted errors.
- Liveness/readiness endpoints, request IDs, restricted CORS, security headers, and safe artifact paths.
- Dataset validation, controlled analytics operations, evidence IDs, and finding-to-action traceability.
- One professional case study report, one editable native PowerPoint presentation, and one reproducible Project Files ZIP with print-ready styling and evidence traceability.
- Reconnectable frontend with recent-run history, progress, failures, retries, and artifacts.
- Deterministic golden evaluations and automated backend/frontend checks.
- Cross-platform Chromium Playwright execution and a GitHub frontend release gate.
- Controlled-pilot configuration guardrails, writable-data readiness, and bounded standalone dataset retention.
- Windows setup, start, and stop commands with local logs.
- Dataset preview, explicit analysis-plan approval, question-coverage checks, structured table/list/narrative editing, version history, editable Word exports, and PDF exports.
- Neutral post-Act packaging with deterministic traceability, population, source/licence, process-integrity, and unsupported-causal-language gates.
- A chief manager, three domain managers, and seven bounded specialist contracts with sanitized, success-validated experience memory.

## Required before public or multi-user launch

1. Add sign-in and organization-level authorization to every session and artifact endpoint.
2. Move data and artifacts to encrypted object storage with retention and deletion rules.
3. Replace the in-process worker with a managed queue when running multiple API replicas.
4. Add centralized monitoring, structured logs, cost/latency metrics, and alerts.
5. Add rate limits, malware scanning, secret rotation, backups, and restore drills.
6. Run acceptance tests with diverse real business datasets and record analytical accuracy.
7. Complete privacy, licensing, and data-processing documents for the target organizations.
8. Derive `MEMORY_SCOPE` from authenticated tenant identity and add operator controls to retire or delete lessons before enabling cross-user memory.

The system is appropriate for local portfolio and controlled pilot use. It must not be marketed as a secure public SaaS until these gates are complete.

Operational setup, retention, health contracts, and the browser-visible API-key limitation are documented in [OPERATIONS.md](OPERATIONS.md).
