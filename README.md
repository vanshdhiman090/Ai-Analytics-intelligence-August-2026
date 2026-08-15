# AI Root Cause Investigation Agent

Given a business KPI movement and structured data, this agent systematically investigates why the metric changed, ranks evidence-backed contributors, tests competing explanations, communicates uncertainty, and recommends the next analytical action.

It is built for analysts, product teams, and operations teams facing a movement such as **Revenue down 8.8%** and needing a reproducible investigation—not another dashboard tile or an unsupported chatbot answer.

## The problem

Dashboards are good at showing **what** changed. They rarely maintain an investigation state, test several explanations, reconcile signed contributions, or know when the evidence is unsafe.

A one-shot language-model answer has the opposite problem: it may sound analytical without proving that its numbers tie back to the dataset.

This product separates analytical judgment from calculation:

```text
KPI movement
  → validate the data and period comparison
  → plan bounded dimension hypotheses
  → run deterministic contribution tests
  → select and recursively investigate supported segments
  → test competing explanations and falsification checks
  → verify evidence and compile a bounded conclusion
  → communicate caveats and the next analytical action
```

Calculations run in deterministic Python over typed contracts. The language model may assist bounded planning and next-test prioritization, but it cannot calculate the result, execute generated Python or SQL, alter server-owned thresholds, or bypass validation. Invalid or unavailable provider output falls back to deterministic control.

**A leading tested contributor is descriptive evidence, not a confirmed causal root cause.** Unsafe data produces an abstention rather than a confident story.

## Engineering proof

Verified at checkpoint `44baf43`:

| Evidence | What it establishes |
| --- | --- |
| **289 maintained backend tests passed locally; 1 legitimate skip** | Contracts, deterministic calculations, API mapping, failure handling, retention, readiness, and regression behavior are exercised. |
| **16 Playwright browser tests** | The workspace preserves signed arithmetic, uncertainty, failure recovery, accessibility, responsiveness, and non-causal language. |
| **Backend and frontend GitHub Actions gates** | Pull requests and `main` pushes must pass Python tests, a production Next.js build, and Chromium Playwright tests. |
| **5/5 controlled real-world robustness scenarios** | The public RCA V1 runtime handled a clear driver, competing explanations, a data-quality abstention, no material driver, and a non-revenue operations case. This is bounded benchmark coverage—not a production-accuracy claim. |
| **Real browser → API → RCA engine smoke test** | The deterministic revenue fixture completed through dataset upload, profiling, the public V1 API, governed investigation services, and the real frontend result view. |
| **Operational hardening** | Request IDs, sanitized failures, deterministic provider fallback, readiness checks, and bounded dataset retention support local and controlled-pilot operation. |

The separate ten-incident RCA scorer includes answer keys and release thresholds. Its bundled reference predictions calibrate the scorer; they are deliberately **not** presented as production-agent accuracy.

## Hero investigation

The included [`demo-data/rca-revenue-incident.csv`](demo-data/rca-revenue-incident.csv) contains a controlled ecommerce incident:

| KPI | January 2026 | February 2026 | Movement |
| --- | ---: | ---: | ---: |
| Revenue | €16,000 | €14,600 | **-€1,400 (-8.75%)** |

The verified investigation path is:

```text
Global revenue -€1,400
  └─ Germany -€1,200 (85.71% of total movement)
       └─ Mobile -€1,100 (91.67% of Germany movement)
            └─ Returning -€1,400 (127.27% of Mobile movement)
```

The deepest contribution legitimately exceeds 100% because New customers offset the decline by **+€300**. At the global level, France provides a **+€200** offset. The agent preserves those signed offsets and reconciles each tested partition instead of clamping percentages or ranking absolute percentages alone.

Result: **Returning customers within Germany → Mobile are the leading tested contributor**. Readiness is `ready_with_caveats`; robustness is not verified at the selected deepest target; the depth-three policy boundary is explicit. This is a mathematical contribution path, not causal proof.

See the complete recruiter-facing walkthrough in [Hero demo](docs/HERO_DEMO.md) and the answer key in [fixture ground truth](demo-data/rca-revenue-incident-ground-truth.md).

## Current RCA architecture

```text
Next.js investigation workspace
             ↓
POST /datasets → validation + deterministic profiling
             ↓
POST /v1/rca/investigations
             ↓
FastAPI public contract + governed dataset loader
             ↓
Governed RCA V1 runtime
  ├─ typed investigation state and hypotheses
  ├─ deterministic KPI and signed-contribution math
  ├─ bounded planner/controller with deterministic fallback
  ├─ scoped data-quality gates
  ├─ falsification and verification
  └─ deterministic conclusion compiler
             ↓
Evidence-backed public response → frontend presentation

PostgreSQL: metadata and durable broader-workflow state
GitHub Actions: backend tests + frontend build + Chromium gate
Local governed storage: bounded upload lifecycle and retention
```

The public RCA endpoint is synchronous and returns a fresh investigation ID. Clients provide a dataset ID, explicit additive KPI, baseline and comparison periods, and approved candidate dimensions. The server owns depth, materiality, data-quality, reconciliation, verification, and conclusion policies.

Historical general-analytics workflow components remain in the repository, but they are not presented as the primary RCA V1 request path. See [Architecture](docs/ARCHITECTURE.md) for the distinction.

## Why this is an agent

- **Not a dashboard:** it does more than render a KPI. It selects bounded next tests and carries evidence forward through an investigation path.
- **Not a chatbot:** claims must be supported by typed evidence, deterministic arithmetic, reconciliation, and explicit quality gates.
- **Not a one-shot prompt:** it maintains structured investigation state, updates hypothesis status, recursively scopes into supported segments, tests alternatives, and can abstain.
- **Auditable:** the public result links the KPI movement, selected scopes, contribution arithmetic, quality issues, conclusion, and evidence references.
- **Self-critical by design:** planning is separate from deterministic execution and verification; weak, competing, or unsafe evidence limits the conclusion.

## Key engineering decisions

| Decision | Why it matters |
| --- | --- |
| Deterministic math over LLM arithmetic | KPI values and contribution shares remain reproducible and testable. |
| Strict typed contracts | Planner, controller, executor, conclusion compiler, and API cannot silently change data shapes. |
| Server-owned RCA policy | Clients cannot tune thresholds until a preferred answer appears. |
| Data-quality abstention | Missing periods, unsafe coverage, or invalid metrics stop interpretation before a false business conclusion. |
| Scoped evidence and quality | A downstream limitation does not erase valid upstream evidence, and upstream verification is not attached to a deeper target. |
| Signed reconciliation | Downward pressure, positive offsets, net movement, and residual within each tested decomposition remain mathematically distinct. |
| Bounded recursive depth | The agent can drill down without creating an unbounded search or pretending it tested every possible explanation. |
| Validated provider fallback | Provider failure cannot remove deterministic analytical correctness. |
| Non-causal conclusion compiler | Mathematical contribution is never silently upgraded into causal certainty. |
| Request IDs and sanitized errors | Failures are diagnosable without returning prompts, stack traces, credentials, paths, or raw rows. |
| Controlled dataset lifecycle | Standalone uploads and finished-session datasets are removed under a tested TTL policy. |
| Backend and browser CI | Numerical semantics and user-facing epistemic language are both release-gated. |

## Quickstart on Windows

Requirements: Python, Node.js/npm, and a PostgreSQL database. Gemini is optional for RCA because deterministic fallback is supported.

1. Run `Setup-Agent.cmd` once.
2. Copy `backend/.env.example` to `backend/.env`.
3. Set `DATABASE_URL`; retain the documented local defaults unless you understand the controlled-pilot settings. Add `GEMINI_API_KEY` only if provider-assisted planning is desired.
4. Apply the SQL files in `backend/migrations` in numeric order to a fresh database.
5. Run `Start-Agent.cmd`.
6. Open [http://127.0.0.1:3010](http://127.0.0.1:3010).
7. Upload `demo-data/rca-revenue-incident.csv` and enter:

| Field | Value |
| --- | --- |
| KPI name | `Revenue` |
| Metric column | `revenue` |
| Time column / grain | `date` / `month` |
| Unit | `EUR` |
| Baseline / comparison | `2026-01` / `2026-02` |
| Candidate dimensions | `country`, `device`, `customer_type`, `acquisition_channel` |

Expected path: **Germany → Mobile → Returning**, with a -€1,400 incident, +€300 target-level offset, zero target-decomposition residual, and explicit non-causal caveats.

Run `Stop-Agent.cmd` when finished. Runtime logs are written to `runtime-logs/`. The step-by-step browser check is in [REAL_RCA_SMOKE_TEST.md](demo-data/REAL_RCA_SMOKE_TEST.md).

## Verification

Backend maintained suite:

```powershell
cd backend
$env:CHECKPOINT_BACKEND="memory"
$env:DATABASE_URL="sqlite+pysqlite:///:memory:"
python -m pytest -q
```

Frontend release gate:

```powershell
cd frontend
npm ci
npm run build
npm run test:e2e
```

Robustness benchmark fixtures and answer keys are documented in [`demo-data/benchmarks/`](demo-data/benchmarks/). CI runs the maintained backend suite plus the frontend production build and Chromium tests.

## Public RCA API boundary

- `POST /datasets` validates and profiles a CSV/XLSX upload and returns an opaque dataset ID.
- `POST /v1/rca/investigations` executes the governed synchronous investigation.
- The public result includes KPI movement, selected path, leading contributor, target decomposition, readiness, target-applicable robustness, caveats, data-quality codes, next action, and response-local evidence references.
- Internal prompts, provider output, mutable agent state, raw rows, filesystem paths, stack traces, and internal evidence identifiers are not exposed.

The broader historical platform still includes session workflows, artifacts, evaluations, experience memory, and read-only Google connectors. Those capabilities are background—not the primary specialist product story.

## Honest limitations

This repository is appropriate for a local portfolio demo and a controlled single-workspace pilot. It is **not** a public multi-user production SaaS.

- Additive `SUM` KPI investigations over structured CSV/XLSX data only
- Synchronous RCA endpoint
- Server-governed maximum depth of three
- Local file storage and process-local active-dataset protection
- No public user authentication, authorization, or tenant isolation
- No distributed queue, execution, locking, or idempotency
- No object storage, malware scanning, or enterprise secret manager
- Browser-visible `NEXT_PUBLIC_API_KEY` is a pilot access gate, not a secret or public authentication mechanism
- No causal inference claim; the engine identifies tested descriptive contributors
- Controlled benchmarks establish regression coverage, not universal analytical accuracy

See [Operational guide](docs/OPERATIONS.md), [Production readiness](docs/PRODUCTION_READINESS.md), and [Interview story](docs/INTERVIEW_STORY.md).

## Broader platform background

The repository began as a human-guided **Ask → Prepare → Process → Analyze → Share → Act** analytics workspace with LangGraph checkpoints, specialist roles, document packaging, governed memory, and Google data connectors. Those components remain available and documented, but the current portfolio product leads with the narrower, evaluated RCA investigation path.
