# Recruiter demo deployment

## Purpose and boundary

Recruiter demo mode lets a visitor run the real governed RCA V1 investigation against the maintained ecommerce benchmark without installing the repository or supplying a file. It is a bounded public portfolio demonstration mode, not public SaaS authentication or tenant isolation.

The mode does not add reasoning behavior, change RCA thresholds, or publish a stored answer. It changes only how the dataset enters the existing product path.

## Architecture

```text
Vercel-hosted Next.js workspace
  -> POST /v1/demo/datasets/hero
  -> backend copies the bundled demo-data/rca-revenue-incident.csv fixture
  -> existing validation, profiling, dataset registry, and lifecycle
  -> opaque dataset UUID returned to the browser
  -> POST /v1/rca/investigations
  -> unchanged governed RCA V1 runtime
  -> sanitized public RCA response
```

Each demo load creates a fresh governed copy and dataset record. The browser never receives a filesystem path. The copy follows the normal dataset retention and delete lifecycle.

## Security boundary

When `RECRUITER_DEMO_MODE=true`:

- `POST /datasets` rejects browser-supplied files server-side.
- `POST /datasets/sql` rejects arbitrary SQL snapshots.
- Google connector catalog, preview, and snapshot endpoints reject access.
- `POST /v1/demo/datasets/hero` is the only supported dataset entry point and selects a fixed server-owned path; the request cannot name a file.
- RCA still accepts only an opaque registered dataset UUID and retains its existing server-owned calculations, depth, validation, and conclusion policy.
- errors remain sanitized and request-correlated.

These controls reduce the public demo's data-ingestion and data-retention risk. They do not add user identity, authorization, tenant isolation, quotas, distributed locks, rate limiting, abuse prevention, or a private browser secret. If `NEXT_PUBLIC_API_KEY` is configured, it is visible in browser code and is only an access gate.

## Required environment variables

Backend:

```text
RECRUITER_DEMO_MODE=true
DEPLOYMENT_MODE=controlled_pilot
DATABASE_URL=<managed PostgreSQL connection URL>
CHECKPOINT_BACKEND=postgres
DATA_DIR=<writable persistent data directory>
CORS_ORIGINS=https://<frontend-host>
API_KEYS=<at least one 16+ character access-gate value>
MEMORY_SCOPE=<unique demo workspace name>
```

`GEMINI_API_KEY` remains optional. The validated deterministic fallback must keep the demo correct when the provider is absent or unavailable.

Frontend (set at build time):

```text
NEXT_PUBLIC_API_BASE_URL=https://<backend-host>
NEXT_PUBLIC_RECRUITER_DEMO_MODE=true
NEXT_PUBLIC_API_KEY=<same optional browser-visible access-gate value>
```

Do not place database credentials, provider keys, refresh tokens, or other secrets in any `NEXT_PUBLIC_` variable. `NEXT_PUBLIC_API_BASE_URL` remains the only backend location source; no production URL is hard-coded.

## Hosting requirements

The frontend is prepared for Vercel. The backend host must support a persistent Python web service, the repository's bundled `demo-data` directory, a writable persistent `DATA_DIR`, HTTPS, explicit CORS, health probes, and the configured request duration for the synchronous RCA endpoint. A managed PostgreSQL database is recommended for deployed metadata and checkpoint compatibility.

Ephemeral local disk is not sufficient for the current dataset lifecycle unless the backend platform deliberately provides a persistent mounted volume. Horizontal multi-replica operation is outside this mode because dataset files and active-use locks are process-local. Deploy one backend instance for the bounded demo.

## Exact smoke test

1. Confirm `GET /health/live` returns `200` and `GET /health/ready` reports `ready`.
2. Open the frontend and confirm **Try validated demo** is shown and no file input or replace-upload control is present.
3. Select **Try validated demo** and confirm the dataset profile shows 320 rows for `rca-revenue-incident.csv`.
4. Configure Revenue as `SUM(revenue)`, `date` at month grain, EUR, baseline `2026-01`, comparison `2026-02`, and candidate dimensions `country`, `device`, and `customer_type`.
5. Start the investigation. Confirm the real response shows January EUR 16,000, February EUR 14,600, movement EUR -1,400 (-8.75%), and the selected path Germany -> Mobile -> Returning.
6. Confirm the deepest selected contribution is EUR -1,400 (127.3% of its parent), positive offsets are EUR +300, and reconciliation residual is EUR 0.
7. Confirm the conclusion is `leading_tested_contributor`, readiness is `ready_with_caveats`, selected-target robustness is not verified, and the UI retains the descriptive-not-causal boundary.
8. Exercise copy summary, public JSON export, and both themes. Confirm exported data contains no path, prompt, credential, raw row, provider error, or internal agent state.
9. Send a direct multipart request to `POST /datasets` and confirm it returns `403 external_dataset_ingestion_disabled` with a request ID.

## Unsupported capabilities

- arbitrary public CSV or Excel upload
- SQL or connector ingestion
- public user accounts or organization authorization
- tenant-isolated storage or memory
- multi-replica backend execution
- unbounded or asynchronous public jobs
- causal proof, forecasting, AutoML, dashboard building, or general chat

## Rollback or disable

Set backend `RECRUITER_DEMO_MODE=false` and restart the backend. Rebuild/redeploy the frontend with `NEXT_PUBLIC_RECRUITER_DEMO_MODE=false` (or unset) because public Next.js variables are frozen into the browser bundle at build time. This restores the existing local-development upload UI and endpoint behavior; it does not delete existing dataset records. Use the documented lifecycle policy for cleanup.

If the public demo must be taken offline immediately, remove public routing to both services first, then disable the flags before restoring any controlled local or pilot environment.
