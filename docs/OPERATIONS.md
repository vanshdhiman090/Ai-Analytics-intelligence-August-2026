# Operational guide

## Supported operating envelope

The RCA V1 product supports local development and controlled, single-workspace pilot operation. It is not a secure public multi-user SaaS.

Use `DEPLOYMENT_MODE=development` for a developer machine, `test` for isolated automation, and `controlled_pilot` for a bounded pilot. Controlled-pilot startup fails unless API keys are configured, every key is at least 16 characters, CORS origins are explicit without `*`, and `MEMORY_SCOPE` is changed from the local default.

The current API-key mechanism is only an access gate. `NEXT_PUBLIC_API_KEY` is bundled into browser-visible frontend code and must never be treated or described as a secret. It does not provide user identity, authorization, tenant isolation, or safe public-SaaS authentication.

## Required configuration

- `DATABASE_URL`: application database; PostgreSQL is required when `CHECKPOINT_BACKEND=postgres`.
- `DEPLOYMENT_MODE`: `development`, `test`, or `controlled_pilot`.
- `CHECKPOINT_BACKEND`: `postgres` for durable workflow checkpoints or `memory` for tests.
- `DATA_DIR`: writable governed local storage, never a filesystem root.
- `MAX_UPLOAD_BYTES`: positive upload limit; default 25 MB.
- `FILE_TTL_DAYS`: positive retention period; default 7 days.
- `MEMORY_SCOPE`: stable workspace namespace; set an explicit unique value for a pilot.
- `CORS_ORIGINS`: explicit browser origins for a pilot.
- `API_KEYS`: required for a controlled pilot, disabled only in local development/test.

`LLM_PROVIDER=gemini` is the supported provider configuration. `GEMINI_API_KEY` enables provider-assisted planning, but provider availability is not a readiness dependency for RCA: deterministic fallback preserves the governed calculations and non-causal conclusion boundaries. Google connector credentials are optional and do not make connector availability a core readiness dependency.

Never commit `.env`, database credentials, Gemini keys, Google tokens, refresh tokens, or OAuth client secrets.

## Dataset retention

The hourly cleanup applies `FILE_TTL_DAYS` to:

- standalone datasets created by uploads, SQL snapshots, or connectors; and
- datasets belonging to sessions that are both finished (`complete` or `error`) and older than the cutoff.

Recent datasets and datasets belonging to active/paused sessions are preserved. An in-process RCA investigation temporarily protects its dataset from cleanup. Eligible files and their `Dataset` rows are removed together. Already-missing files result in row cleanup. One failed file is logged by dataset ID and does not stop other records; it remains eligible for the next pass.

This is a single-process controlled-pilot policy. Cross-replica active-use coordination and object-storage lifecycle rules are not implemented.

## Health and lifecycle

- `GET /health/live` is dependency-light and answers whether the process is serving HTTP.
- `GET /health/ready` checks database connectivity and that `DATA_DIR` can be created and written. It returns HTTP 503 with bounded status fields when either is unavailable.
- LLM and optional connector availability are not readiness requirements.
- Startup validates configuration and marks interrupted runs as failed/retryable.
- Shutdown cancels and awaits the cleanup task before stopping the run manager.
- Cleanup failures are logged and remain non-fatal to the application.

## Release commands

Backend:

```powershell
cd backend
$env:CHECKPOINT_BACKEND="memory"
$env:DATABASE_URL="sqlite+pysqlite:///:memory:"
python -m pytest -q
```

Frontend:

```powershell
cd frontend
npm ci
npm run build
npm run test:e2e
```

GitHub Actions runs the maintained backend suite plus a Node 22 frontend job using `npm ci`, a Chromium-only Playwright installation, the production build, and the semantic browser suite. CI sends the generated browser report to ignored `test-results/` storage so it does not modify the tracked release report.

## Not solved for public production

- public user authentication and organization authorization
- tenant and per-user data/storage isolation
- backend-for-frontend sessions that keep credentials out of browser code
- distributed idempotency, queues, workers, and cross-replica cleanup coordination
- encrypted object storage, quotas, malware scanning, and reverse-proxy request limits
- rate limiting and abuse protection
- centralized structured logs, metrics, traces, alerts, and audit retention
- managed secret storage/rotation, backups, and restore drills
- formal privacy, licensing, and data-processing controls

These are architectural blockers, not labels that the controlled-pilot mode attempts to hide.
