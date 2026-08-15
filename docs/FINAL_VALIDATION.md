# Final validation and release-candidate audit

## Decision

**RELEASE CANDIDATE: PASS**

The AI Root Cause Investigation Agent passed the Phase 5C engineering acceptance audit for local portfolio demonstration and controlled single-workspace pilot use. This decision does not claim public-SaaS readiness, causal validation, or universal analytical accuracy.

## Validation record

- Baseline commit: `4040493` — Add professional UI themes and capability foundation
- Validation date: 2026-08-15
- Starting working tree: clean
- Public execution mode: synchronous
- RCA calculations and API semantics: unchanged

## Verified production-demo path

The code-backed request path is:

1. Next.js `RcaWorkspace` uploads a structured file with `POST /datasets`.
2. FastAPI validates, stores, and profiles the dataset and returns an opaque dataset UUID.
3. The workspace submits the bounded public request to `POST /v1/rca/investigations`.
4. The RCA router resolves the server-owned dataset and protects its active lifecycle.
5. The RCA API service validates requested columns and periods, applies server-owned maximum depth and policy, and maps the request into `SingleLevelInvestigationRequest`.
6. `run_single_level_investigation` performs deterministic KPI, contribution, data-quality, reconciliation, verification, and conclusion work. Optional provider assistance can select only allowed next tests; failure falls back deterministically.
7. The response mapper returns the typed public RCA contract, which `InvestigationResult` renders without exposing mutable internal runtime state.

## Real hero investigation

The maintained `demo-data/rca-revenue-incident.csv` fixture was uploaded and investigated through the real browser, API, database-backed dataset registry, and governed RCA runtime.

| Check | Observed result |
| --- | --- |
| Baseline | January 2026 Revenue: €16,000 |
| Comparison | February 2026 Revenue: €14,600 |
| Movement | -€1,400; exact -8.75% (UI rounds to -8.8%) |
| Selected path | Germany → Mobile → Returning |
| Germany | -€1,200; 85.7% of total movement |
| Mobile within Germany | -€1,100; 91.7% of parent movement |
| Returning within Germany → Mobile | -€1,400; 127.3% of parent movement |
| Deepest positive offset | +€300 |
| Deepest tie-out | Parent -€1,100 = leader -€1,400 + remaining +€300; residual €0 |
| Conclusion | Leading tested contributor; bounded by maximum depth |
| Readiness | Ready with caveats |
| Target robustness | Not verified at selected target; no incorrect upstream inheritance |
| Interpretation | Descriptive contribution evidence, not causal proof |

The UI preserved the valid contribution above 100%, explained that positive offsets make this possible, and did not clamp the value. France's +€200 global offset is present in the fixture and benchmark answer key. The current public response intentionally exposes the selected path and deepest selected decomposition rather than every segment in every tested upstream decomposition; this is recorded as a visibility limitation, not a mathematical discrepancy.

## Controlled robustness benchmark

The maintained real-world runner passed 5 of 5 answer-keyed scenarios through the real RCA V1 runtime:

| Scenario | Result |
| --- | --- |
| Clear ecommerce driver | Passed: Germany → Mobile → Returning, signed offsets preserved, maximum-depth boundary explicit |
| Competing explanations | Passed: `competing_explanations`, no manufactured winner |
| Unsafe data | Passed: `data_quality_abstention` after detected incomplete comparison coverage |
| Diffuse/no material driver | Passed: `inconclusive` with `no_material_driver` |
| Non-revenue operations KPI | Passed: Europe → Carrier B → Warehouse North |

The runner reported `READY` using deterministic fallback. This is bounded regression evidence and must not be described as production accuracy.

## Automated release gates

### Backend

- Command environment: `CHECKPOINT_BACKEND=memory`, isolated temp directory, repository virtual environment
- Result: **289 passed, 1 skipped, 0 failed** in 43.30 seconds
- Skip: unavailable external Nike comparison-context source
- Warning: one Starlette `TestClient`/HTTPX deprecation warning

### Frontend

- `npm run build`: **passed**; optimized Next.js production build completed
- `npm run test:e2e`: **19 passed, 0 failed** in 57.9 seconds
- Browser coverage includes signed arithmetic, scoped robustness, data-quality abstention, no-material behavior, maximum-depth wording, structured failures, retry safety, duplicate submission protection, dataset replacement, responsive layout, keyboard operation, themes, copy summary, and public JSON export.

## Semantic and UI acceptance

- No rendered claim of confirmed/proven root cause, causal driver, guarantee, or universal certainty was found.
- KPI movement, leading tested contributor, signed offsets, reconciliation, decomposition residual, evidence, robustness, data quality, readiness, and next action remain distinct.
- Maximum-depth language recommends further analysis without implying a user-accessible depth control.
- Dark mode is readable and is the default.
- Light mode is readable, uses a purpose-designed palette, and preserves semantic distinctions.
- Theme preference survives reload.
- The shell presents AI Analytics Intelligence and Root Cause Investigation as the only active capability; no fake capability navigation is exposed.
- Copy summary succeeded and included the explicit non-causal interpretation boundary.
- Public JSON export is generated from an explicit allow-list of the public RCA response; browser tests verified the downloaded content contains no prompt, path, secret, provider data, or mutable agent state.
- At 390 × 844, the page had no horizontal overflow and critical controls remained reachable.
- Form labels, keyboard activation, visible focus treatment, non-color status text, and announced copy feedback were verified.

One obvious presentation defect was found and fixed: the global investigation-path heading and description could run together. The path now uses the existing block layout class, with an end-to-end regression assertion.

## API and operational boundaries

The public response mapper exposes only the version, investigation ID, KPI movement, selected investigation path, leading contributor, selected decomposition, conclusion, data quality, and supporting evidence. It does not expose prompts, raw provider output, filesystem paths, stack traces, credentials, raw rows, or mutable internal state. Expected failures remain structured and include a request ID. Dataset references are opaque UUIDs, while depth, thresholds, and verification policy remain server owned.

These controls do not provide full public-SaaS security. The accepted operating envelope remains a local portfolio demo or controlled single-workspace pilot. Public production still requires real authentication and authorization, tenant isolation, distributed execution and locking, object storage, malware scanning, rate limiting, managed secrets, centralized observability, and horizontal worker coordination.

## Documentation corrections

- Updated the maintained Playwright count from 16 to 19 in `README.md` and `docs/INTERVIEW_STORY.md`.
- Corrected `docs/ARCHITECTURE.md` so the direct public RCA service path is distinguished from the legacy `RootCauseAgent` adapter and RCA V1 cannot be read as publishing causal conclusions.

## Known limitations and technical compromises

- The RCA API is synchronous. During the live run, the configured optional Gemini provider repeatedly returned 503/high-demand responses. Deterministic fallback preserved correctness, but provider retries extended the result latency to roughly two to three minutes.
- The public V1 response does not expose the complete segment table for every upstream tested decomposition, so the global France +€200 offset is benchmark-verified but not separately rendered in the result UI.
- The in-app browser automation could not capture a native download event during the live click. The export implementation, explicit public-field allow-list, and downloaded JSON contents are covered by the passing Playwright release test.
- The first local backend attempts exposed environment setup issues: PostgreSQL checkpoint access when memory mode was omitted and Windows temp-directory permissions without an approved isolated path. The final prescribed isolated run passed completely apart from the documented external-data skip.
- The existing Starlette/HTTPX deprecation warning should be removed in a future dependency-maintenance pass.

None of these limitations is a correctness, epistemic-safety, public-contract, or major UX blocker within the declared release envelope.
