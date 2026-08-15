# Interview story: AI Root Cause Investigation Agent

These are speaking notes for explaining the project accurately. They describe the repository and its engineering decisions; they do not imply employment, customer adoption, or production-scale deployment.

## 30-second explanation

I built an AI Root Cause Investigation Agent for analysts, product teams, and operations teams facing a KPI movement. Instead of generating a one-shot explanation, it validates the data, maintains typed investigation state, tests approved dimensions with deterministic contribution math, recursively follows supported segments, checks competing explanations, and publishes an evidence-linked non-causal conclusion. The LLM can help prioritize bounded next steps, but it never calculates the result or executes generated code, and the system falls back deterministically when the provider fails.

## 2-minute explanation

The problem is that dashboards tell teams that Revenue fell, while generic AI tools can produce a plausible “why” without proving their arithmetic. I narrowed the product to one specialist job: investigate an additive KPI movement over structured business data.

The user uploads a dataset, defines the KPI and two periods, and approves candidate business dimensions. The FastAPI service maps that request into strict internal contracts. The engine checks period coverage and metric completeness before analysis. It then creates explicit hypotheses, runs deterministic signed contribution tests, records evidence, updates hypothesis status, and follows the strongest supported segment through a bounded depth. It preserves negative pressure and positive offsets, so a valid contribution can exceed 100% without being clamped.

Planning and next-step selection may use an LLM, but every proposal is constrained and validated. Invalid, unsafe, or unavailable provider output uses a deterministic fallback. Verification and the conclusion compiler are separate from planning. The final API exposes the KPI movement, selected path, decomposition, data-quality status, caveats, readiness, robustness at the correct scope, next action, and safe evidence references—not prompts or mutable agent state.

The proof is layered: 289 maintained backend tests passed locally, 19 Playwright browser tests cover the public experience, both suites are gated in GitHub Actions, five controlled real-world robustness scenarios pass through the public RCA V1 runtime, and a real browser-to-engine revenue investigation has been verified. Those benchmarks demonstrate controlled behavior, not universal production accuracy.

## Architecture explanation

```text
Next.js RCA workspace
  → dataset upload and profile
  → FastAPI V1 RCA contract
  → governed local dataset loader
  → typed investigation request/state
  → bounded hypothesis planner/controller
  → deterministic contribution engine
  → scoped data-quality and falsification checks
  → verification
  → deterministic conclusion compiler
  → sanitized public response
```

PostgreSQL supports the broader application's metadata and durable workflows. GitHub Actions gates backend correctness plus the frontend production build and Chromium semantic tests. Local dataset retention and health endpoints support the controlled-pilot operating envelope.

The key separation is: the model may propose an allowed next analytical action, deterministic code computes evidence, and a separate compiler decides the strongest statement the evidence permits.

## Hardest engineering problems

### 1. Contribution is not causality

**Problem:** A segment can account for most of a KPI movement without causing it.

**Decision:** The contracts distinguish mathematical observations, leading tested contributors, robust descriptive explanations, competing explanations, abstention, and inconclusive results. The UI and conclusion compiler prohibit unsupported causal upgrades.

**Why it matters:** A numerically correct system can still be analytically dangerous if its language overstates the evidence.

### 2. Contributions above 100% can be correct

**Problem:** Returning customers contribute -€1,400 while the parent Mobile decline is only -€1,100.

**Decision:** Preserve signed segment contributions and positive offsets. Returning is 127.27% because New customers offset +€300; `-€1,400 + €300 = -€1,100`.

**Why it matters:** Clamping to 100% or ranking percentage drops alone destroys reconciliation and hides offsetting behavior.

### 3. Downstream data quality must not erase valid upstream evidence

**Problem:** A deep segment may have insufficient rows even when an upstream contribution is valid.

**Decision:** Attach quality issues and robustness to explicit scopes. A downstream block limits deeper claims without retroactively invalidating the upstream finding.

**Why it matters:** Investigation state must preserve what is known, where it is known, and where the evidence stops.

### 4. Provider failure cannot break analytical correctness

**Problem:** LLM calls can time out, fail, or return invalid actions.

**Decision:** Validate every proposal against allowed dimensions, prior tests, data health, non-causal language, and iteration budgets. Reject unsafe proposals and continue with deterministic fallback.

**Why it matters:** The model improves prioritization; it is not a single point of correctness.

### 5. Failure recovery must preserve user work safely

**Problem:** Network, upload, dataset-expiry, and server failures can occur after the user configured an investigation.

**Decision:** Return bounded errors with request IDs, keep recoverable form state, prevent duplicate in-flight submissions, delete superseded uploads, and never expose provider errors, paths, rows, or stack traces.

**Why it matters:** Professional analytical software must behave predictably when the happy path fails.

### 6. Operational reliability spans backend and browser semantics

**Problem:** Unit tests alone cannot detect a UI that turns “leading contributor” into “confirmed root cause.” Standalone uploads also need a lifecycle.

**Decision:** Gate deterministic backend tests and Playwright semantic assertions in CI; add writable-storage readiness, clean task shutdown, and tested TTL cleanup for standalone datasets.

**Why it matters:** The public wording and operating behavior are part of analytical correctness.

## Tradeoffs

- **Synchronous V1 endpoint:** simpler request semantics and easier traceability, but unsuitable for long-running or horizontally distributed investigations.
- **Maximum depth three:** bounds search and demo latency, but can stop before the next useful descriptive segment.
- **Explicit candidate dimensions:** prevents uncontrolled exploration, but relies on the user to supply meaningful business axes.
- **Local file storage:** appropriate for a portfolio and controlled pilot, but not for multi-instance production.
- **Process-local dataset protection:** prevents same-process cleanup races, but does not coordinate replicas.
- **Additive `SUM` KPI only:** supports exact reconciliation, but intentionally rejects ratios, funnels, distinct counts, and non-additive metrics until governed semantics exist.
- **No causal inference:** keeps claims honest, but the agent cannot confirm a behavioral mechanism from contribution data alone.
- **Deterministic fallback:** protects correctness and availability, though its priority choices may be less context-sensitive than a valid model proposal.

## What I would build next for enterprise deployment

I would not add forecasting, dashboards, or more agents first. I would harden the operating boundary:

1. real user and organization authentication;
2. tenant-scoped authorization for every dataset and investigation;
3. encrypted object storage with retention, malware scanning, and deletion controls;
4. asynchronous jobs with durable queues, idempotency, cancellation, and progress events;
5. centralized logs, metrics, traces, alerts, and cost monitoring;
6. managed secrets, rate limits, backups, and restore drills;
7. broader answer-keyed datasets with measured failure categories;
8. only then, governed support for additional KPI identities and business domains.

## Likely technical interview questions

### Why not let the LLM calculate contributions?

Because arithmetic must be deterministic, reproducible, and exactly testable. The model receives bounded summaries to prioritize tests; Python computes the values and reconciliation.

### How do you know the agent is improving rather than sounding smarter?

I use controlled scenarios with known answer keys, score the actual public RCA runtime, preserve regression fixtures, and gate changes in backend and browser CI. Reference predictions calibrate the scorer; they are not agent-accuracy evidence.

### What does “robust” mean here?

It means a descriptive explanation survived the implemented verification checks at a specific selected scope. It does not mean causal certainty, and upstream robustness is not attached to a deeper target.

### Why is a 127% contribution not a bug?

Because signed offsets exist. A -€1,400 segment contribution plus a +€300 offset reconciles to the -€1,100 parent movement. Net contribution shares need not be bounded by 100%.

### How does the system handle incomplete data?

It checks required fields, date semantics, period presence, comparison coverage, metric nulls, and scoped row sufficiency. A blocking failure returns an analytical abstention rather than a fabricated driver.

### How is this different from a decision tree over dimensions?

The path is not just a greedy ranking. The runtime maintains hypotheses and evidence, tests every eligible dimension within governed scopes, checks competing decompositions, preserves offsets and reconciliation, applies scoped quality gates, verifies conclusions, and can stop or abstain.

### What prevents prompt injection or generated-code risk?

The public RCA request accepts typed data references and bounded fields—not arbitrary Python or SQL. Model output must match strict action contracts and cannot alter calculations or policy. Model-written code is never executed.

### Is it production ready?

It is ready for local portfolio use and a controlled single-workspace pilot. It is not a secure public SaaS because authentication, tenant isolation, distributed execution, object storage, and centralized operations are intentionally not claimed.

### What would make you change the materiality or depth rules?

Benchmark evidence. I would add controlled failure cases, measure the impact of the proposed policy change, and change the server-owned contract only if it improves the target cases without regressing existing behavior.

### What is the biggest remaining product risk?

Confusing a mathematically dominant segment with a real-world mechanism. The next analytical step should collect mechanism-level evidence, not just add more polished language.
