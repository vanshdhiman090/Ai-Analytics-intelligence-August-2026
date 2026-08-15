# Architecture

## Current portfolio product: RCA V1

The primary product path is the **AI Root Cause Investigation Agent**. It accepts one validated structured dataset, an explicit additive KPI and period comparison, and approved candidate dimensions. It returns a scoped, evidence-backed descriptive conclusion without exposing internal agent state.

```text
Next.js RCA workspace
  → POST /datasets → validation and deterministic profiling
  → POST /v1/rca/investigations
  → governed dataset resolver and typed request mapping
  → governed RCA V1 runtime
       ├─ hypothesis planning and bounded next-test control
       ├─ deterministic KPI and signed-contribution calculations
       ├─ scoped data-quality gates
       ├─ falsification and verification
       └─ deterministic conclusion compiler
  → sanitized public result and evidence references
```

Provider output can prioritize an allowed next test but cannot calculate results, execute code, change policy, or bypass validation. Rejected or unavailable provider output uses deterministic fallback. The API owns the maximum depth, materiality, reconciliation, coverage, verification, and conclusion rules.

PostgreSQL supports metadata and the broader durable workflow. Local governed files support the controlled single-workspace operating envelope. Backend tests, the frontend production build, and Chromium Playwright semantics are gated by GitHub Actions.

The manager/specialist hierarchy and Ask → Prepare → Process → Analyze → Share → Act workflow below are broader platform background. They should not be interpreted as the primary execution path for `POST /v1/rca/investigations`.

## Broader analytics platform background

## Product promise

The workspace converts a user-supplied tabular dataset and a decision question into a reviewable decision package. It follows Google's **Ask → Prepare → Process → Analyze → Share → Act** framework, but every stage has an explicit input contract, output contract, quality gate, and audit record.

The LLM interprets intent and proposes plans. Controlled application code reads data, performs transformations, calculates statistics, and renders charts. A model must never invent a metric value or execute arbitrary code.

## Non-negotiable principles

1. **Ground or ask:** infer only what the supplied evidence supports; request external context explicitly.
2. **Plan, execute, verify:** the model proposes a typed plan, an allow-listed executor computes it, and validators check the result.
3. **Trace every claim:** recommendation → finding → evidence → operation → dataset version.
4. **Conservative processing:** never silently impute, delete, winsorize, or redefine a field.
5. **Durable by default:** workflow state and artifacts survive process restarts and deployments.
6. **Tenant isolation:** every dataset, run, checkpoint, and artifact belongs to an authenticated workspace.

## Stage contracts

### 1. Ask

Input: rough user request.

Output: `AnalysisBrief` with objective, decision, primary question, stakeholders, success criteria, scope, assumptions, constraints, and missing context.

Gate: a human approves or revises the brief. Typing “Confirm” retains the proposed question; it is not stored as the question itself.

### 2. Prepare

Input: approved brief and immutable dataset version.

Output: source inventory, ROCCC assessment, schema profile, semantic types, privacy flags, quality issues, and question-to-data feasibility assessment.

Gate: pause only for material external context or a blocking ambiguity. Routine facts derivable from the file are handled automatically.

### 3. Process

Input: dataset version and approved cleaning plan.

Output: new immutable dataset version, transformation manifest, before/after quality metrics, rejected-row sample, and reproducible code reference.

Gate: destructive or meaning-changing transformations require approval. Trimming whitespace and exact duplicate handling may follow workspace policy.

### 4. Analyze

Input: approved brief, processed dataset, and profile.

Output: typed `AnalysisPlan`, deterministic operation results, evidence registry, findings, uncertainty, and unresolved questions.

Supported operations begin with descriptive summaries, grouped aggregations, trends, distributions, correlations, contribution analysis, and anomaly checks. Every operation validates column existence, data type, population, denominator, and minimum sample size.

Gate: a coverage validator checks whether the plan answers the confirmed question; a claim validator rejects findings without evidence.

### 5. Share

Input: evidence-backed findings.

Output: chart specifications, rendered artifacts, executive summary, methodology, evidence table, and limitations.

Gate: chart choice and encodings are validated against the evidence shape. The UI displays artifacts and findings, never local filesystem paths.

### 6. Act

Input: findings, decision context, and constraints.

Output: prioritized actions with owner role, timeframe, impact, effort, supporting finding IDs, monitoring metrics, and stop/review conditions.

Gate: every action must cite valid findings; every finding must cite computed evidence. Unknown impact stays “unknown.”

### Neutral package step (not an analytical phase)

Input: the completed outputs from Ask through Act.

Output: one editable case study report with Word/PDF exports, one editable native PowerPoint presentation, one reproducible Project Files ZIP, and a saved report revision history.

Gate: publication is blocked when evidence/finding/action links are broken, populations are missing, source/licence context is absent, integrity checks fail, or descriptive evidence is presented with unsupported causal language. Package does not calculate findings or create recommendations.

## Runtime components

```text
Next.js workspace
  ├─ upload / analysis brief / approvals
  ├─ live run timeline
  └─ decision report and evidence explorer
             │
FastAPI application
  ├─ authentication and workspace authorization
  ├─ dataset and artifact APIs
  ├─ read-only Google connector pack (Drive, Sheets, GA4, Search Console, BigQuery)
  ├─ run API with streaming events
  └─ background-job submission
             │
LangGraph workflow
  ├─ stage nodes and conditional quality gates
  ├─ durable PostgreSQL checkpointer
  └─ idempotent side effects
             │
Domain services
  ├─ LLM gateway with structured output, retry, and cost logging
  ├─ dataset profiler and conservative processor
  ├─ allow-listed analysis planner/executor
  ├─ evidence and claim validators
  └─ chart renderer plus structured Word/PDF/HTML document packager
             │
PostgreSQL + object storage
  ├─ users, workspaces, runs, datasets, versions, and audit events
  ├─ evidence, findings, recommendations, prompt versions, and evaluations
  └─ uploaded data, charts, and reports in private object storage
```

## Manager and specialist hierarchy

```text
LangGraph workflow controller
  └─ AnalyticsManager — planning, typed delegation, supervision, audit, and memory policy
       ├─ DiscoveryManager
       │    ├─ BusinessProblemSpecialist
       │    ├─ StakeholderScopeSpecialist
       │    └─ KPISpecialist
       ├─ DataManager
       │    ├─ DataIntakeSpecialist + PrepareAgent profiling executor
       │    ├─ SchemaSpecialist + DataQualitySpecialist
       │    └─ PrivacyBiasSpecialist + ProcessAgent + CleaningSpecialist
       ├─ AnalysisManager
       │    ├─ AnalysisPlannerSpecialist + StatisticalAnalysisSpecialist
       │    ├─ TrendSegmentationSpecialist + RootCauseAgent
       │    │    ├─ governed metric semantics (Revenue V0)
       │    │    └─ typed RCA engine (contribution, hypotheses, falsification, reconciliation, abstention)
       │    └─ EvidenceSpecialist
       ├─ DeliveryManager
       │    ├─ VisualizationSpecialist + NarrativeSpecialist
       │    └─ RecommendationSpecialist + DocumentSpecialist
       └─ QualityManager (independent from producing roles)
            ├─ CalculationReviewer + EvidenceCritic
            ├─ CausalLanguageReviewer + PublicationReviewer
            └─ MemoryCuratorSpecialist
```

### Root-cause capability boundary

The language model may propose the approved analysis plan and evidence-linked narrative. It cannot calculate the RCA result. The RootCauseAgent maps an approved additive `segment_change` operation to `RCASemanticDefinition`; `app/services/root_cause.py` then calculates the incident movement, signed driver contributions, explained residual, evidence strength, and hypothesis status from typed inputs. A causal conclusion requires high-strength causal evidence plus completed falsification checks. Otherwise the strongest permitted conclusion is a mathematical driver, or an explicit abstention.

The Revenue V0 layer in `app/domain/revenue_semantics.py` uses exact physical-field aliases and publishes only measurable driver-tree branches. It never fuzzy-matches business fields. The current generic executor cannot yet enforce all Revenue filters and distinct-count identities, so those capabilities remain declared gaps rather than simulated calculations.

The release gate is two-layered: the existing deterministic operation suite and a controlled 10-incident RCA scorecard. `combine_with_analytical_release()` preserves legacy category scores and requires both analytical gates before browser readiness can make the complete release ready.

The full machine-readable role catalogue is defined in `backend/app/agent/hierarchy.py`. Executable least-privilege field maps and typed task/result envelopes are defined in `backend/app/agent/manager.py` and `backend/app/agent/specialist_contracts.py`. Domain managers pass a copied bounded assignment to specialists, so supervision metadata and recalled lessons do not mutate durable workflow state. Independent reviewers can approve or return exact revision reasons, but cannot rewrite evidence or findings.

### Google Intelligence Connector Pack

`backend/app/services/google_connectors.py` is a Data Manager service, not a
general-purpose browsing layer. It provides five independently testable
read-only adapters behind one contract: Drive metadata, Sheets ranges, GA4
reports, Search Console performance queries, and BigQuery `SELECT`/`WITH`
queries. `POST /connectors/preview` returns a bounded, source-labelled preview;
`POST /connectors/snapshot` persists the result as a normal dataset with
retrieval time, source URI, request fingerprint/parameters, and an explicit
read-only marker. The service never persists tokens, full query text, raw
provider error bodies, or arbitrary Google actions. The existing Prepare and
Quality gates therefore remain the source of truth after a connector read.

### Governed experience memory

The `agent_memories` table is retrieval memory, not autonomous model training. Its lifecycle is:

```text
sanitized failure → candidate lesson → successful retry → active lesson
                                             ↓
                         recalled only for the same workspace + specialist + stage
```

Secrets, tracebacks, full prompts, and row data are not intentionally stored. Error text is bounded and common credential patterns are redacted. Memory is fail-open: if memory storage is unavailable, the governed analytical pipeline continues without it. Active lessons are advisory and cannot bypass user instructions, allow-listed operations, typed contracts, human approvals, or release gates.

### Retry recovery before the first checkpoint

Every new session stores a bounded `run_input` envelope containing source references, hashes, the analytical request, selected objectives, and workflow mode. It contains no raw dataset rows or credentials. Retry first resumes the existing LangGraph checkpoint. Only an explicit `EmptyInputError` permits the manager to restart from this saved envelope; unrelated failures are never hidden by an automatic restart. Legacy sessions without either a checkpoint or saved input receive a clear instruction to start a new analysis.

## Why this is not a “swarm”

The product may use specialized planner, analyst, critic, and reporter roles, but they are bounded capabilities inside one governed workflow. Adding many agents does not improve quality by itself. Typed contracts, deterministic tools, evidence validation, durable state, and evaluations provide the professional advantage.
