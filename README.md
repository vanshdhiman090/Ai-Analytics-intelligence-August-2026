# AI Analytics Workspace

A human-guided analytics agent that follows the Google Data Analytics lifecycle:

**Ask → Prepare → Process → Analyze → Share → Act**

It accepts one or multiple CSV/XLSX sources and a business question, discovers and validates table relationships, pauses when human approval or external context is required, executes only allow-listed analytical operations, and produces an evidence-linked decision package.

## What it produces

- One complete case study report covering Ask, Prepare, Process, Analyze, Share, and Act, with findings, recommendations, caveats, source context, and embedded charts.
- An editable native PowerPoint presentation with stakeholder-ready narrative, charts, recommendations, next steps, and source notes.
- One Project Files ZIP containing the cleaned dataset, charts, a reproducible notebook and Python code, the approved analysis plan, validated evidence, and raw-data references.
- An editable report workspace with version history and downloadable Word or PDF exports.
- A durable run record that can recover after browser or backend restarts.

## Architecture

```text
Next.js workspace → FastAPI API → bounded run workers → LangGraph workflow
                           ↘ PostgreSQL sessions + durable checkpoints
                           ↘ validated local datasets + report artifacts
                           ↘ read-only Google Intelligence Connector Pack
```

Key design rules:

- Ground or ask: never invent provenance, licensing, intent, or stakeholder context.
- Controlled computation: the model proposes typed operations; model-written Python is never executed.
- Traceability: evidence IDs support findings, and finding IDs support recommendations.
- Durable approvals: PostgreSQL checkpoints resume the correct stage after a restart.
- Pre-checkpoint recovery: the sanitized original run envelope is persisted, so Retry can safely restart a run that failed before its first LangGraph checkpoint.
- Coverage gate: plans cannot silently omit dataset columns explicitly named in the question.
- Multi-file model gate: shared keys are profiled for uniqueness, coverage, cardinality, orphan records, and row-multiplication risk before any join is approved.
- Many-to-many relationships are blocked; approved one-to-many grain expansion and unmatched rows remain visible in the Process-phase audit.
- Release readiness combines the deterministic analytical suite with source-aware Playwright browser journeys; any frontend source change makes the browser gate stale until `npm run test:e2e` passes again.
- Honest uncertainty: missing data, invalid dates, sample limits, and correlation caveats remain visible.
- Clean phase boundaries: Act creates actions; a neutral post-phase Package step validates and assembles documents without becoming a seventh analytical phase.

## Managed specialist workforce

The LangGraph run controls durable stage order while `AnalyticsManager` acts as chief orchestrator. Five domain managers supervise 24 bounded professional specialists: Discovery, Data, Analysis, Delivery, and an independent Quality Manager. The chief manager creates typed assignments, exposes only allow-listed state fields to each specialist, validates required outputs, retries only classified transient side-effect-free work, and records sanitized supervision events. Every specialist has a declared mission, responsibilities, inputs, outputs, allowed actions, quality gates, and escalation conditions in `backend/app/agent/hierarchy.py`.

Broad stage executors are wrapped by focused roles. For example, Analyze is separated into planning, deterministic statistical execution, trend/segmentation review, root-cause diagnostics, and evidence review. The independent quality team reviews calculation integrity, citations, causal language, and final publication readiness without modifying the producer's evidence or findings.

### Root Cause Analytics V0

Root-cause mode now turns an approved additive `segment_change` calculation into a typed investigation report. The deterministic engine verifies the incident and baseline, checks data health, ranks signed driver contributions, reconciles explained and unexplained movement, evaluates competing hypotheses and falsification checks, grades evidence strength, and abstains when the evidence is unsafe. Mathematical contribution is never presented as causal proof. Completed RCA projects expose a dedicated **Investigation** view alongside the normal evidence and audit views.

Revenue is the first governed business semantic contract: `SUM(net_revenue)` at order grain with explicit completed-order, refund, reporting-currency, timezone, and comparison policies. Exact field bindings are required. Missing or ambiguous required fields—and missing currency/timezone policy—produce an auditable abstention rather than a guessed metric.

Release evaluation now combines the original 27 deterministic analytics cases with 10 answer-keyed RCA incidents covering detection, incident classification, driver/segment identification, contribution accuracy, hypothesis status, abstention, reconciliation, causal safety, and evidence traceability. The included RCA reference predictions calibrate the scorer; they are not represented as a production-agent accuracy claim.

The agent also keeps a governed experience memory in PostgreSQL. Failures start as inactive candidates. A candidate becomes an active lesson only when a later retry succeeds, and only active lessons for the same workspace, specialist, and stage are recalled. Recalled lessons are advisory: current user instructions, typed contracts, deterministic validation, and quality gates always take priority. Set `MEMORY_SCOPE` to a unique stable workspace/tenant identifier before deployment.

### Read-only Google Intelligence Connector Pack

The Data Manager can now take bounded, read-only snapshots from Google Drive, Google Sheets, GA4, Search Console, and BigQuery. Each adapter returns the same preview and lineage shape, applies a source-specific row limit, and converts an approved read into a normal dataset for the existing Prepare/Process/Analyze workflow. Google credentials are process configuration only. `GOOGLE_ACCESS_TOKEN` supports a quick test; durable local access uses `GOOGLE_REFRESH_TOKEN`, `GOOGLE_OAUTH_CLIENT_ID`, and `GOOGLE_OAUTH_CLIENT_SECRET`, with renewed access tokens held only in memory. Credentials are never stored in the database, prompts, memory lessons, or dataset rows. BigQuery accepts only one `SELECT`/`WITH` query and all five adapters are exposed through `GET /connectors/catalog`, `POST /connectors/preview`, and `POST /connectors/snapshot`.

## Run on Windows

For the current configured project, double-click `Start-Agent.cmd`, then open:

**http://127.0.0.1:3010**

Double-click `Stop-Agent.cmd` when finished.

For a fresh computer:

1. Double-click `Setup-Agent.cmd` once.
2. Copy `backend/.env.example` to `backend/.env`.
3. Add the Neon database URL and Gemini API key.
4. Apply the SQL files in `backend/migrations` in numeric order.
5. Run `Start-Agent.cmd`.

Runtime logs are written to `runtime-logs/`.

## Verification

Backend tests:

```powershell
cd backend
$env:CHECKPOINT_BACKEND="memory"
.\.venv\Scripts\python.exe -m pytest tests -q
```

Deterministic analytics evaluations:

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.evals.runner
```

This versioned release gate checks exact calculations, contribution reconciliation, period comparisons, null and date handling, method-question alignment, unsafe column/type rejection, uncertainty language, non-causal correlation boundaries, outlier suitability, and deterministic repeatability. It writes:

- `backend/evals/reports/latest.json` for automation and regression tracking.
- `backend/evals/reports/latest.html` for human review.

Every critical case and every evaluation layer must pass. The same gate is available inside the workspace UI and through `POST /evaluations/run`.

Frontend production build:

```powershell
cd frontend
npm run build
```

## API lifecycle

- `POST /datasets` validates and uploads a dataset.
- `POST /data-model/inspect` profiles up to ten uploaded sources and returns detected relationships plus a conservative proposed join model.
- `POST /sessions` queues a new analysis and returns immediately.
- `GET /sessions/{id}` returns progress, checkpoints, errors, and artifacts.
- `POST /sessions/{id}/resume` answers a human checkpoint.
- `POST /sessions/{id}/retry` safely continues from the durable checkpoint.
- `GET /sessions` returns recent analyses.
- `GET/PUT /artifacts/{id}/editor` loads and saves versioned document content.
- `GET /artifacts/{id}/download.docx` creates an editable Word export from the latest saved revision.
- `GET /artifacts/{id}/download.pdf` creates a print-ready PDF from the same saved revision.
- `GET /health/live` and `GET /health/ready` support operational health checks.
- `GET /evaluations/latest` returns the latest accuracy and regression result.
- `POST /evaluations/run` reruns the deterministic release gate and refreshes its reports.
- `GET /agent/hierarchy` describes every manager and specialist contract.
- `GET /agent/memory` returns the current workspace's sanitized candidate and active lessons.
- `GET /connectors/catalog` reports the five data-only, read-only Google sources and setup readiness.
- `POST /connectors/preview` reads a bounded source preview without creating a dataset.
- `POST /connectors/snapshot` creates a lineage-tagged dataset from an approved connector read.

## Current readiness

This is strong for local portfolio work and controlled pilots. Public multi-user deployment still requires authentication/authorization, encrypted object storage, a distributed job queue, monitoring, rate limits, backups, and formal privacy controls. See [Production readiness](docs/PRODUCTION_READINESS.md).
