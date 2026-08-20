<div align="center">

![AI Root Cause Investigation Agent](assets/01-hero-banner.svg)

### AI Root Cause Investigation Agent

An evidence-governed analytics agent that investigates why a business KPI moved — through deterministic contribution analysis, bounded hypothesis testing, self-verification, and explicit uncertainty instead of confident-sounding narrative.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-336791?logo=postgresql&logoColor=white)](https://neon.tech/)
[![Gemini API](https://img.shields.io/badge/Gemini-API-8B5CF6?logo=google&logoColor=white)](https://ai.google.dev/)
[![Tests](https://img.shields.io/badge/Tests-323%20backend%20%C2%B7%2024%20browser-2EAD33?logo=pytest&logoColor=white)](#testing)
[![CI](https://github.com/vanshdhiman090/Ai-Analytics-intelligence-August-2026/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/vanshdhiman090/Ai-Analytics-intelligence-August-2026/actions/workflows/backend-tests.yml)

**🔗 [Live app](https://ai-root-cause-investigation-agent.vercel.app)** · **[GitHub](https://github.com/vanshdhiman090/Ai-Analytics-intelligence-August-2026)**

**Current specialist capability:** Root Cause Investigation<br>
**Application shell:** AI Analytics Intelligence

</div>

<!--
DEMO GIF SLOT — record and save as assets/demo.gif, then replace this comment with:
![AI Root Cause Investigation Agent Demo](assets/demo.gif)

Recommended recording: upload dataset → configure KPI and periods → run investigation
→ show the drill-down path → show the data-quality caution → show readiness and robustness
-->

---

## What this is

The AI Root Cause Investigation Agent investigates a defined movement in an additive business KPI using structured tabular data. It is built for analysts, product teams, operations teams, and decision-makers asking questions such as:

> Why did Revenue fall from January to February?

Instead of returning a one-shot explanation, the agent validates the dataset and periods, turns approved business dimensions into bounded hypotheses, calculates signed segment contributions deterministically, follows supported evidence through a governed investigation path, tests competing explanations, checks reconciliation, verifies the scope of its own evidence, and reports caveats, readiness, and robustness separately.

Its strongest output is a **leading tested contributor** or, when verification supports it at the selected scope, a **robust descriptive explanation**. Neither is causal proof, and the system says so.

## Why it matters

Dashboards tell teams **what changed**. An analyst still has to slice dimensions, compare periods, reconcile totals, test alternative explanations, inspect missing data, and decide what the evidence can safely support. That work is slow, inconsistent between analysts, and easy to get subtly wrong.

A generic LLM chatbot creates the opposite failure: it produces a fluent explanation without tying its arithmetic back to the dataset. Fluency is not evidence.

This platform closes that gap with a governed investigation loop:

```text
structured investigation state
→ bounded analytical tests
→ deterministic evidence
→ verification and stopping rules
→ scoped conclusion with explicit uncertainty
```

It is an analytical investigation workspace — not a dashboard builder, an open-ended CSV chatbot, or an autonomous causal-discovery system.

---

## Table of contents

- [Product overview](#product-overview)
- [Business problem](#business-problem)
- [Product solution](#product-solution)
- [System architecture](#system-architecture)
- [How the investigation works](#how-the-investigation-works)
- [When a correct number is not an answer](#when-a-correct-number-is-not-an-answer)
- [Hero investigation](#hero-investigation)
- [Why this is an agent](#why-this-is-an-agent)
- [AI reasoning vs deterministic calculation](#ai-reasoning-vs-deterministic-calculation)
- [Engineering proof](#engineering-proof)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Usage](#usage)
- [Testing](#testing)
- [Public API boundary](#public-api-boundary)
- [Roadmap](#roadmap)
- [Business impact](#business-impact)
- [Data quality and limitations](#data-quality-and-limitations)
- [Security and operational boundary](#security-and-operational-boundary)
- [Author](#author)

---

## Product overview

The user uploads one CSV or XLSX dataset, defines an additive `SUM` KPI, selects baseline and comparison periods, and approves candidate dimensions. The system profiles the data, executes a bounded investigation, and presents:

- the signed KPI movement;
- the selected investigation path;
- the leading tested contributor at each scope;
- downward pressure, positive offsets, and reconciliation tie-out;
- target-scoped evidence strength and robustness;
- data-quality findings and caveats;
- explanatory readiness; and
- the recommended next analytical action.

The Next.js workspace includes recoverable errors, duplicate-submission protection, responsive layouts, persistent light/dark themes, bounded summary copy, and an allow-listed public JSON export.

## Business problem

Teams investigating a KPI movement commonly face four problems:

- **Manual slicing** — the analyst repeatedly filters geography, device, channel, product, or customer segments by hand.
- **Misleading percentages** — a large percentage decline can be immaterial to total KPI movement, while offsets can make valid contribution shares exceed 100%.
- **Weak evidence discipline** — data-quality incidents and competing explanations are easily overlooked when there is pressure to produce an answer.
- **Unsupported narratives** — a plausible correlation gets presented as a cause without a causal design.

The product makes this workflow reproducible and explicit: hypotheses → tests → evidence → updated status → deeper scope → verification → bounded conclusion.

## Product solution

| Capability | What it does |
|---|---|
| Structured dataset ingestion | Accepts bounded CSV/XLSX uploads, profiles the dataset deterministically, and returns an opaque dataset identifier. |
| Numeric role classification | Classifies every numeric column at profiling time as quantity, identifier, cyclical, or discrete scale. Only genuine quantities are offered as additive KPIs; a column matching the active time grain is excluded as a dimension. |
| Governed KPI configuration | Requires an explicit additive KPI, time field, grain, baseline, comparison, and approved dimensions. |
| Bounded hypothesis investigation | Represents candidate dimensions as hypotheses and executes only allowed analytical actions. |
| Deterministic contribution analysis | Calculates KPI movement and signed segment contributions in Python — not in an LLM. |
| Recursive investigation path | Scopes into supported segments up to a server-governed maximum depth of three. |
| Competing-explanation testing | Avoids manufacturing one winner when several decompositions are genuinely competitive. |
| Segment reliability verification | Rejects a leading segment its own raw data cannot support: too few backing rows, a category structurally absent from one period, or a fully null baseline. |
| Placeholder-label governance | Detects segment labels that record a data gap rather than a business category (`Not Defined`, `Unknown`, `N/A`). Their movement still counts toward reconciliation, but they cannot carry a descriptive explanation. |
| Signed reconciliation | Preserves downward pressure, positive offsets, remaining segment movement, and reconciliation tie-out. |
| Evidence and uncertainty | Publishes evidence references, strength, caveats, readiness, and robustness at the applicable scope. |
| Provider fallback observability | Every degradation to the deterministic path is logged with the `investigation_id`, so a specific investigation can be traced to the path that produced it. |
| Release-gated validation | Gates deterministic backend behavior and public browser semantics in GitHub Actions. |

---

## System architecture

![System Architecture](assets/02-system-architecture.svg)

Data flows through a governed request path with a single responsibility per layer:

1. **Next.js investigation workspace** — collects the dataset and bounded configuration.
2. **`POST /datasets`** — validates the upload, profiles it deterministically, stores it under a governed local lifecycle, and returns an opaque UUID.
3. **`POST /v1/rca/investigations`** — validates the public typed contract and resolves the server-owned dataset.
4. **Governed RCA service** — maps public inputs into internal investigation contracts while keeping maximum depth and analytical thresholds server-owned.
5. **Deterministic investigation runtime** — calculates KPI movement, signed contributions, offsets, scoped quality checks, and reconciliation.
6. **Verification and conclusion compiler** — limits the conclusion to what the evidence supports.
7. **Public response mapper** — exposes only the typed result the frontend requires.

PostgreSQL (Neon) stores application metadata. Uploaded analysis files use governed local storage with retention controls. GitHub Actions gates backend tests, the Next.js production build, and Chromium Playwright tests.

The repository still contains a historical `RootCauseAgent` adapter and a broader LangGraph workflow. That adapter is **not** the execution path for `POST /v1/rca/investigations`.

## How the investigation works

![Investigation Workflow](assets/03-investigation-workflow.svg)

At each tested scope, the runtime maintains typed investigation state and performs a controlled loop:

1. validate required columns, date semantics, period presence, coverage, and KPI completeness;
2. create or prioritize hypotheses from the approved dimensions;
3. execute deterministic contribution tests;
4. store the evidence from every test;
5. update each hypothesis as supported, weak, rejected, or unresolved;
6. select a material contributor by contribution to total movement — not percentage decline alone;
7. scope one level deeper when evidence and depth policy allow;
8. test competing explanations and run five verification challenges; and
9. compile the strongest bounded conclusion plus a recommended next action.

The investigation can stop without a confident winner:

| Condition | Public behavior |
|---|---|
| Unsafe or incomplete data | `data_quality_abstention` or a scoped caveat |
| Genuinely competing evidence | `competing_explanations` |
| No sufficiently material tested contributor | `inconclusive / no_material_driver` |
| Maximum depth reached | Bounded descriptive conclusion plus a next analytical action |

---

## When a correct number is not an answer

The arithmetic was never the hard part. Signed contribution analysis is deterministic and reconciles exactly. The difficult problem is knowing when an arithmetically correct result should **not** be presented as a business explanation.

Adversarial testing against real datasets surfaced four distinct versions of that failure. Each is now governed:

| Failure mode | Before | Now |
|---|---|---|
| **Thin evidence** | A segment backed by a single row was reported as a strong contributor. | Per-segment row counts are captured before aggregation collapses them. Insufficient sample forces a weakened verdict and a not-ready readiness. |
| **Structural absence** | A category present in the baseline and absent from the comparison was reported as a total decline. | Absence is distinguished from a measured drop. A renamed, discontinued, or pipeline-broken category cannot be certified as the explanation. |
| **Fabricated baseline** | A fully null baseline was silently read as zero, manufacturing a decline that was never measured. | A null baseline is reported as unavailable, not as a movement. |
| **Semantically empty labels** | `Size: Not Defined` — a data-entry gap covering 30% of rows — was selected as the leading contributor and drilled into two levels deeper. | Placeholder labels are detected at profiling time, surfaced in the setup wizard *before* the investigation runs, and blocked from carrying a descriptive explanation. |

The design rule across all four is the same: **suppress the claim, keep the arithmetic.** Excluding an untrustworthy segment from the totals would break the additive tie-out that makes the decomposition auditable. Promoting the runner-up instead would present a less complete picture as though it were the whole story. Refusing to certify is the only honest option.

The same principle governs column selection. A numeric column is not automatically a valid KPI: summing an identifier, an hour-of-day, or a five-point rating scale is arithmetically valid and analytically meaningless.

## Hero investigation

The controlled ecommerce fixture [`demo-data/rca-revenue-incident.csv`](demo-data/rca-revenue-incident.csv) contains 320 order-level rows across two complete monthly periods.

| KPI | January 2026 | February 2026 | Movement |
|---|---:|---:|---:|
| Revenue | €16,000 | €14,600 | **-€1,400 (-8.75%)** |

Real browser-to-runtime validation selected:

```text
Global Revenue                         -€1,400
└── Germany                            -€1,200   85.7% of global movement
    └── Mobile                         -€1,100   91.7% of Germany movement
        └── Returning                  -€1,400  127.3% of Mobile movement
```

### Why 127.3% is valid

The Returning-customer segment applies more downward pressure than the final Germany → Mobile movement because another segment offsets part of the decline:

```text
Returning contribution                -€1,400
New-customer positive offset             +€300
                                       -------
Germany → Mobile movement              -€1,100
Reconciliation residual                     €0
```

`127.3%` is a signed contribution share — not confidence, not an error, not causal certainty. The UI preserves the value instead of clamping it to 100%.

**Published outcome:** leading tested contributor · `ready_with_caveats` · selected-target robustness not verified · bounded by maximum depth · descriptive contribution evidence, not causal proof.

See the [complete hero walkthrough](docs/HERO_DEMO.md) and [fixture ground truth](demo-data/rca-revenue-incident-ground-truth.md).

## Why this is an agent

This is not a static dashboard or a one-shot prompt. The system maintains structured investigation state and moves through a bounded analytical process. It selects among allowed next tests, carries hypotheses and evidence across scopes, updates hypothesis status after deterministic tests, follows a supported segment deeper, challenges its own leading explanation, verifies evidence at the correct scope, stops when evidence is unsafe or insufficient, abstains instead of forcing a story, and recommends what to test next.

The agent controls **what to test next** within policy. Deterministic Python controls **what the numbers are**. Verification controls **what may be claimed**.

## AI reasoning vs deterministic calculation

![AI and Deterministic Boundary](assets/04-ai-deterministic-boundary.svg)

The LLM's role is narrow and deliberate: it influences **order**, never outcome.

Gemini participates at three points — proposing which dimension to test first, choosing the next investigation action, and ordering verification challenges. In all three cases the deterministic layer force-appends anything the model omits, so the complete dimension set is always tested and every applicable verification challenge always runs. This was verified by tracing every call site, not assumed from design intent.

The model **cannot**:

- calculate KPI or contribution values;
- skip a dimension, shrink the tested set, or stop an investigation early;
- invent evidence or execute generated Python or SQL;
- change server-owned thresholds or maximum depth;
- bypass data-quality, reconciliation, or verification gates; or
- upgrade descriptive evidence into causal proof.

Its one user-visible output is a written pre-test rationale, surfaced explicitly as *"why this was checked — written before any results were known"* — never as justification for the answer. Provider failure, timeout, or malformed output triggers deterministic fallback, logged with the `investigation_id` so a degraded run is traceable rather than silent.

## Engineering proof

| Verified evidence | Result | What it establishes |
|---|---:|---|
| Maintained backend suite | **323 passed · 1 skip · 0 failed** | Contracts, deterministic calculations, API mapping, lifecycle, failure handling, regression behavior. |
| Browser release suite | **23 passed · 0 failed** | Public semantics, signed arithmetic, failure recovery, accessibility, responsiveness, themes, safe export. |
| Recruiter-demo browser suite | **1 passed · 0 failed** | Public demo path renders end to end without a configured provider. |
| Frontend production build | **Passed** | Next.js production compilation succeeds. |
| Controlled RCA benchmark | **5/5 scenarios passed** | Bounded regression coverage across deliberately different RCA behaviors. |
| GitHub Actions | **Backend and frontend gates passed** | Release checks run on pull requests and `main`. |

The five controlled scenarios cover a clear ecommerce contributor, competing explanations with no manufactured winner, unsafe data producing `data_quality_abstention`, diffuse movement producing `inconclusive / no_material_driver`, and a non-revenue operations KPI. Three also assert row-shuffle invariance.

These establish bounded regression coverage. They do **not** establish universal analytical accuracy, autonomous causal discovery, or public-production readiness. The full record is in [Final validation](docs/FINAL_VALIDATION.md).

---

## Technology stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 18, responsive CSS |
| Backend / API | Python 3.13, FastAPI, Uvicorn, Pydantic contracts |
| Deterministic analytics | pandas, NumPy, typed RCA domain contracts |
| Database | PostgreSQL (Neon Cloud) via SQLAlchemy; SQLite for isolated CI tests |
| Dataset formats | CSV and XLSX via pandas / openpyxl |
| Agent control | Governed planner and controller services with deterministic fallback |
| AI layer | Google Gemini via `google-genai` — not a calculation or readiness dependency |
| Backend testing | pytest |
| Browser testing | Playwright with Chromium |
| CI | GitHub Actions: Python 3.13, Node.js 22 |
| Version control | Git, GitHub |

## Project structure

```text
ai-analytics-workspace/
│
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routes and public RCA contracts
│   │   ├── domain/              # Typed investigation and semantic contracts
│   │   ├── services/            # RCA runtime, control, verification, lifecycle
│   │   ├── agent/               # Broader governed workflow and adapters
│   │   └── evals/               # Answer-keyed evaluation runners
│   ├── migrations/              # Sequential SQL, applied manually
│   └── tests/
│
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js application and theme styles
│   │   ├── components/rca/      # Investigation workflow and result UI
│   │   └── lib/                 # API, presentation, export, capability registry
│   └── e2e/                     # Playwright release suite
│
├── demo-data/                   # Controlled fixtures and ground truth
├── docs/
├── assets/
├── .github/workflows/
├── Setup-Agent.ps1 / .cmd
├── Start-Agent.ps1 / .cmd
└── Stop-Agent.ps1 / .cmd
```

## Installation

**Requirements**

- Windows with PowerShell
- Python 3.13 or later
- Node.js 22 and npm
- A PostgreSQL connection (Neon Cloud or self-hosted)
- A Gemini API key — optional; the system runs deterministically without one

**Setup**

```powershell
git clone https://github.com/vanshdhiman090/Ai-Analytics-intelligence-August-2026.git
cd Ai-Analytics-intelligence-August-2026
.\Setup-Agent.ps1
```

(`.cmd` equivalents are also provided for each launcher script, if preferred.)

Copy `backend/.env.example` to `backend/.env`, set `DATABASE_URL`, then apply the SQL files in `backend/migrations/` in numeric order.

## Environment variables

Create `backend/.env` from `backend/.env.example`. The variables relevant to local setup:

```
DATABASE_URL=
DEPLOYMENT_MODE=development
GEMINI_API_KEY=
MAX_UPLOAD_BYTES=26214400
RECRUITER_DEMO_MODE=false
```

- `DATABASE_URL` — PostgreSQL connection string.
- `DEPLOYMENT_MODE` — `development`, `test`, or `controlled_pilot`; gates which configuration invariants are enforced.
- `GEMINI_API_KEY` — optional; enables provider-assisted dimension prioritization. Without it the system runs deterministically.
- `MAX_UPLOAD_BYTES` — dataset upload size limit in bytes (default 25 MB).
- `RECRUITER_DEMO_MODE` — set `true` for a public demo deployment with a reduced-risk configuration.

See `backend/.env.example` for the complete list, including optional Google connector and checkpoint-backend variables.

Never commit `.env` or any file containing real credentials.

## Usage

```powershell
.\Start-Agent.ps1
```

Open [http://127.0.0.1:3010](http://127.0.0.1:3010), then:

1. Upload a CSV or XLSX dataset.
2. Define the additive KPI, time column, and grain. Non-additive numeric columns are filtered out automatically.
3. Select baseline and comparison periods.
4. Approve candidate dimensions. Placeholder-heavy and circular columns are flagged or excluded before the run.
5. Review the bounded investigation contract, then run it.
6. Read the result: investigation path, contribution arithmetic, data-quality findings, readiness, robustness, caveats, and next action.

```powershell
.\Stop-Agent.ps1
```

## Testing

**Backend**

```powershell
cd backend
$env:CHECKPOINT_BACKEND="memory"
$env:DATABASE_URL="sqlite+pysqlite:///:memory:"
python -m pytest -q
```

**Controlled RCA benchmark**

```powershell
cd backend
python -m app.evals.real_world_rca_benchmark_runner
```

**Frontend**

```powershell
cd frontend
npm ci
npm run build
npm run test:e2e
```

Current results: backend **323 passed, 1 skipped**; Playwright release suite **23 passed**; recruiter-demo suite **1 passed**; controlled benchmark **5/5**; GitHub Actions gates **successful**.

The benchmark runner recomputes ground truth independently in pandas rather than trusting the stored answer key.

## Public API boundary

**`POST /datasets`** — accepts one bounded CSV/XLSX upload, validates and profiles it, stores it under the governed local lifecycle, and returns an opaque dataset identifier plus a bounded profile and preview.

**`POST /v1/rca/investigations`** — accepts the opaque dataset ID, goal, additive KPI definition, two periods, and approved dimensions. Synchronous. Clients cannot control analytical thresholds, maximum depth, verification, or conclusion policy.

The public response contains only the API version and investigation ID, KPI movement, selected investigation path, leading tested contributor, selected target decomposition, conclusion with caveats and readiness and robustness and next action, bounded data-quality status, and response-local supporting evidence references.

It does **not** expose prompts, raw provider output, filesystem paths, stack traces, credentials, raw agent state, or raw dataset rows. Expected failures return sanitized structured errors with request IDs.

Opaque IDs and bounded response mapping are safety controls — they do not constitute public authentication or tenant isolation.

## Roadmap

**Completed**

- Governed RCA V1 public API with typed contracts
- Deterministic signed contribution analysis and reconciliation
- Bounded recursive investigation path
- Five-challenge verification layer, including segment reliability
- Placeholder-label detection across profiling, wizard, and verifier
- Numeric role classification preventing non-additive KPIs and circular dimensions
- Provider fallback with `investigation_id`-correlated structured logging
- LLM prioritization rationale surfaced with explicit pre-test framing
- Guest identity and dataset ownership enforcement
- Next.js investigation workspace with persistent light/dark themes
- Controlled answer-keyed benchmarks and GitHub Actions gates

**Planned**

- Close the drill-down verification gap so challenges evaluate the deepest resolved target
- A migration runner with a tracking table and transactional apply
- Guest rate limits, concurrency caps, and retention windows
- Operator-distinguishable database error surfaces
- Broader answer-keyed evaluation coverage, including live-provider runs
- Additional independent specialist capabilities (forecasting, anomaly detection, scenario analysis) — architectural directions, not commitments

## Business impact

**For analysts and data teams**

- Less repetitive dashboard slicing during KPI investigations
- Contribution arithmetic that is reproducible, reviewable, and reconciles exactly
- Data-quality problems surfaced *before* business interpretation, not after

**For organizations**

- A repeatable hypothesis → test → evidence workflow rather than ad hoc analysis
- Consistent communication of evidence and uncertainty across teams
- Fewer unsupported narrative explanations reaching decision-makers

These are intended workflow benefits. No customer adoption, financial ROI, or measured time-saving claim is made.

## Data quality and limitations

This system is built on the principle that limitations should be surfaced, not hidden. Every entry below was found through adversarial testing against real datasets, diagnosed to root cause, and consciously deferred rather than patched superficially.

| Finding | Detail |
|---|---|
| Verification evaluates the root-level contributor only | On investigations that drill deeper, the verification target no longer matches the conclusion target, and robustness is reported as `not_verified` with an explicit caveat rather than partially applied. The cause is an integration gap: the conclusion resolver walks the investigation path to its deepest node while the verifier reads root-level state that recursion does not update. Two of five challenges are already scope-generic; three hold global values. Honest abstention was chosen over a partial fix that would report one segment's label beside another segment's numbers. |
| Placeholder detection inherits the same boundary | A semantically empty label is caught when it leads at the top level, not when it wins at depth two or below. |
| Percentages and rates classify as quantities | Numeric columns representing percentages, rates, or ratios remain selectable as additive KPIs, though summing them is not meaningful. Cardinality-based detection cannot separate them from genuine quantities; a name-token heuristic was deliberately deferred as lower-confidence. |
| Migrations are applied manually | Raw SQL in numeric order, with no runner or tracking table. This has already caused a real failure: a committed migration was never applied to the hosted database, and every upload failed with a generic error until it was applied by hand. |
| Database errors surface generically | Schema drift, constraint violations, and connection failures all collapse into one client-facing registration error. Not exposing internals is intentional; the absence of any operator-facing distinction is not. |
| No causal inference, by design | The system identifies tested descriptive contributors. Establishing causation requires an experimental or quasi-experimental design the data does not support, and the output language never claims otherwise. |
| Benchmarks are regression evidence, not accuracy | Five controlled scenarios establish that known behaviors do not regress. They do not establish universal analytical accuracy across arbitrary datasets. |
| Single-workspace operating envelope | Supports additive `SUM` KPIs, synchronous requests, a server-governed maximum depth of three, and governed local file storage. Not a secure multi-tenant SaaS. |

See [Known limitations](docs/KNOWN-LIMITATIONS.md) for the maintained record of accepted scoping decisions.

## Security and operational boundary

Implemented controls include request IDs, sanitized errors, readiness checks, guest identity with dataset ownership enforcement, bounded dataset retention, provider fallback, controlled-pilot configuration guardrails, allow-listed public response mapping, and backend and browser CI gates.

The browser-visible `NEXT_PUBLIC_API_KEY` is a pilot access gate — not a secret, and not public authentication.

Before public or multi-user production, the platform would still require user and organization authentication, authorization and tenant isolation, distributed execution with idempotency and locking, encrypted object storage with retention policies, malware scanning and upload abuse protection, rate limiting and quotas, managed secrets with rotation, and centralized logs, metrics, traces, and audit retention.

See [Operations](docs/OPERATIONS.md) and [Production readiness](docs/PRODUCTION_READINESS.md).

## Additional documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Hero demo](docs/HERO_DEMO.md)
- [Interview story](docs/INTERVIEW_STORY.md)
- [Known limitations](docs/KNOWN-LIMITATIONS.md)
- [Capability architecture](docs/CAPABILITY_ARCHITECTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Production readiness](docs/PRODUCTION_READINESS.md)
- [Final validation](docs/FINAL_VALIDATION.md)

## Author

**Created by Vansh Dhiman**

Digital Business & Data Science student, focused on AI agent systems, deterministic analytics, and building AI products that are honest about what they cannot establish.

- GitHub: [github.com/vanshdhiman090](https://github.com/vanshdhiman090)
