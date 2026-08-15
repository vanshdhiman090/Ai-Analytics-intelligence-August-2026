# Capability Architecture

## Product principle

AI Analytics Intelligence is a shared analytics platform that hosts independent specialist analytical capabilities. Root Cause Investigation is the only implemented capability today. Future capabilities must earn their place through a bounded user problem, an explicit contract, deterministic validation, and answer-keyed evaluation.

The platform must not become one universal analytics agent. Shared infrastructure should remove operational duplication; it must not blur the analytical contracts or reasoning policies of different specialists.

## Shared platform infrastructure

The following concerns may be shared across capabilities:

- dataset ingestion and profiling
- governed dataset storage and lifecycle controls
- request IDs and safe error handling
- authentication and access boundaries
- operational health and readiness
- application shell and product identity
- light/dark theme system
- safe, contract-bounded frontend utilities
- continuous integration and release gates

The frontend may keep a small registry for implemented capabilities. It is product metadata, not a plugin framework, and must not expose unavailable capabilities as navigation or controls.

## Specialist capability ownership

Each capability owns its complete analytical boundary:

- public API contract
- domain contracts
- specialist agent or analytical engine
- reasoning and stopping policy
- deterministic calculations
- benchmarks and evaluations
- frontend workflow and presentation semantics
- semantic safety rules

This keeps forecasting logic out of RCA components and prevents RCA investigation state from becoming a generic platform state. Stable RCA backend files should remain where they are unless a concrete product need justifies moving them.

Conceptual API boundaries are:

```text
/v1/rca/...
/v1/forecasting/...          future
/v1/anomaly-detection/...    future
/v1/scenarios/...            future
```

Only `/v1/rca/...` is a current product capability. The future paths above document separation of responsibility; they are not implemented endpoints.

## Frontend extension pattern

Shared interface elements belong in `components/shell/` or `components/shared/`. Capability workflows remain independent:

```text
components/
  shell/
  shared/
  rca/
  forecasting/              future
  anomaly/                  future
  scenario/                 future
```

Adding a capability should add its own workflow and register only an actually available product capability. It should not place specialist logic inside the application shell or retrofit unrelated logic into RCA components.

## Future Forecasting Agent

Forecasting should eventually be a separate specialist capability with its own API, contracts, engine, evaluations, workflow, and semantic safety rules. It must not depend on RCA investigation state.

Potential inputs:

- dataset
- target metric
- date/time column
- forecast horizon
- optional business dimensions or context

A governed future workflow could be:

```text
data validation
→ time-series diagnostics
→ baseline models
→ candidate forecasting models
→ backtesting
→ model comparison
→ uncertainty intervals
→ forecast
→ explanation
→ monitoring recommendation
```

That workflow would require its own deterministic backtesting rules, leakage controls, time-aware benchmarks, uncertainty semantics, and release gates. Model selection would be earned through out-of-sample performance rather than persuasive language. Forecasts would be presented as uncertain estimates, not guaranteed outcomes.

No forecasting library, model, endpoint, or user interface is part of the current phase. This document defines the isolation boundary so that a future implementation can be added without weakening the completed RCA product.
