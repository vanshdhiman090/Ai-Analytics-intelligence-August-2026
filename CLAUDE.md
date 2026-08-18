# CLAUDE.md

Root-level guidance for working in this repository. This file governs the
whole repo. `frontend/CLAUDE.md` (which pulls in `frontend/AGENTS.md`) adds
Next.js-version-drift warnings scoped to `frontend/` only — it does not
override anything here, and it says nothing about the backend.

## Repository layout

```text
backend/
  app/
    api/            FastAPI app factory, auth, versioned RCA contracts, routers/*
    domain/         Typed contracts (root_cause_contracts.py, contracts.py, revenue_semantics.py)
    services/       RCA runtime, control, verification, lifecycle, dataset services
    agent/          Broader LangGraph-based governed workflow (see "app/agent/* path" below)
    evals/          Answer-keyed evaluation and release-gate runners
  migrations/       Sequential raw SQL files, applied manually (see below)
  tests/            Flat pytest suite, no subfolders

frontend/
  src/app/          Next.js application and theme styles
  src/components/   rca/ (investigation workflow + result UI), shell/, shared/
  src/lib/          API client, presentation, export, capability registry
  e2e/              Playwright release suite
```

`backend/app/api/routers/` holds one `APIRouter` per resource: `health`,
`evaluations`, `datasets`, `sessions`, `artifacts`, `agents`, `connectors`,
`demo`, `rca`. All are registered in `backend/app/api/main.py` via
`app.include_router(...)`.

## Running tests and builds

Backend tests:

```bash
cd backend
python -m pytest -q
```

`pytest.ini` sets `testpaths = tests` and `python_files = test_*.py`. CI
(`.github/workflows/backend-tests.yml`) runs this against
`DATABASE_URL=sqlite+pysqlite:///:memory:` with `CHECKPOINT_BACKEND=memory`.

Frontend build and e2e tests:

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium   # first run only
npm run build
npm run test:e2e
npm run test:e2e:recruiter-demo
```

There is no frontend unit-test script — only the two Playwright suites above
(`playwright.config.mjs` and `playwright.recruiter-demo.config.mjs`).

## Migration conventions

Migrations live in `backend/migrations/` as plain SQL files named with a
zero-padded sequential prefix, e.g. `012_guest_dataset_ownership.sql`. There
is no migration-runner tool in this repo (no Alembic, no custom apply
script) — **applying migrations is a manual step**: run the files in
`backend/migrations/` in numeric order against `DATABASE_URL`. This is the
current convention, not a gap to fix; do not build a runner as a side effect
of unrelated work.

Style conventions to follow in new migration files:
- Idempotent DDL: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS ...`
- A short comment at the top of the file stating intent and scope (see
  `011_session_retry_input.sql`, `012_guest_dataset_ownership.sql`)

Backend tests never apply these files. They build schema directly from the
SQLAlchemy ORM models in `app/models/schema.py`
(`Base.metadata.create_all(engine)` against an in-memory SQLite engine — see
"Test layout" below). This means **the ORM model and the migration files
must be kept in sync by hand** whenever either changes.

## RCA engine

Public HTTP entry point: `POST /v1/rca/investigations`, handled by
`create_rca_investigation` in `backend/app/api/routers/rca.py`.

Request/response flow:
- `backend/app/services/rca_api.py` — `load_governed_dataset`,
  `build_internal_request`, `execute_rca_request`, `map_investigation_response`
- `backend/app/services/root_cause.py` — the deterministic calculation
  engine itself: `investigate_root_cause`, `investigate_dataframe`,
  `run_single_level_investigation`, `run_evidence_driven_investigation`,
  `run_hypothesis_planned_investigation`, `run_recursive_investigation`
- `backend/app/domain/revenue_semantics.py` — Revenue V0 metric semantics
  layer (exact physical-field aliases only, no fuzzy matching)

The language model may propose an allowed next test but never calculates
the result — `root_cause.py` owns contribution math, residual movement,
evidence strength, and hypothesis status from typed inputs.

### `app/agent/*` path

`backend/app/agent/` implements the broader Ask → Prepare → Process →
Analyze → Share → Act LangGraph workflow, including
`app/agent/subagents/root_cause_agent.py`. This is a secondary/background
path — it is **not** what `POST /v1/rca/investigations` executes. Treat it
as a separate, still-active part of the platform, not as deprecated code.

## API route organization

Each router file under `backend/app/api/routers/` declares its own
`APIRouter`. Every router except `health` sets
`dependencies=[Depends(require_api_key)]` at the router level.

**Target convention for new routers:** follow the pattern in
`backend/app/api/routers/rca.py`. It defines a custom `APIRoute` subclass
(`RCAAPIRoute`) that normalizes every error — validation errors, typed
service errors, `HTTPException`, and unhandled exceptions — into one
envelope shape:

```json
{"error": {"code": "...", "message": "...", "request_id": "...", "fields": [...]}}
```

via `RCAErrorResponseV1`. New routers should adopt this structured-envelope
pattern.

**Legacy pattern, not yet migrated:** `backend/app/api/routers/datasets.py`
builds ad hoc `JSONResponse` error bodies inline (`_upload_error`) that
happen to match the same shape but aren't backed by the shared `APIRoute`
machinery. Don't take this file as the template for new code — it predates
the `RCAAPIRoute` convention and hasn't been migrated to it.

Guest-scoped resource access always goes through
`owned_dataset_query(db, guest)` (`app/services/datasets.py`), never a raw
`Dataset` query — `GuestPrincipal` is injected via `require_guest_principal`.

## Test layout and naming

Flat `backend/tests/` directory, `test_*.py`, discovered per `pytest.ini`.
No shared `conftest.py`. Each HTTP-level test file defines its own local
helpers (see `test_guest_dataset_ownership.py` for the fullest example):

- `_session_factory()` builds an isolated in-memory SQLite engine and calls
  `Base.metadata.create_all(engine)`
- `@compiles(UUID, "sqlite")` / `@compiles(JSONB, "sqlite")` shims are
  defined per test file to compile the Postgres-only ORM column types
  against SQLite — this is duplicated across files rather than centralized;
  match the existing per-file pattern rather than introducing a shared
  fixture unless asked to.
- `_client(monkeypatch, factory)` patches `SessionLocal` individually on
  each router module that needs it (e.g.
  `app.api.routers.datasets.SessionLocal`), not through a single global
  override
- Test function names are full-sentence descriptions of behavior, e.g.
  `test_second_guest_cannot_delete_first_guests_dataset`

## Error handling, auth, and config conventions

**Error handling:** the `/v1/rca/*` surface standardizes on structured JSON
errors with `request_id` and `code` (see API route organization above).
Domain services raise specific typed exceptions at the point of failure —
`RCAAPIServiceError`, `DatasetProcessingError`, `DatasetRegistrationError`,
`DatasetTooLargeError`, `DatasetUploadError`, `DataModelError`,
`SqlSourceError` — which routers catch at the boundary rather than letting
bare exceptions propagate.

**Auth boundary:** two independent layers in `backend/app/api/auth.py`:
- `require_api_key` — bearer `X-API-Key` header, enforced only when
  `settings.API_KEYS` is non-empty (empty = auth disabled, the local-dev
  default); gates entire routers.
- `require_guest_principal` / `GuestPrincipal` — a backend-signed,
  HMAC-verified anonymous guest cookie (`rca_guest`); scopes row-level
  dataset ownership. The signing key falls back to a process-local dev
  secret unless `GUEST_IDENTITY_SECRET` (≥32 chars) is configured;
  `Settings.validate()` only requires that secret when
  `DEPLOYMENT_MODE == "controlled_pilot"`.

**Config loading:** a single `Settings` class in `backend/app/core/config.py`,
populated from `os.environ` via `python-dotenv`'s `load_dotenv()` and
instantiated once as the module-level `settings`. All cross-field validation
lives in one `Settings.validate()` method, called from the FastAPI
`lifespan` at startup — not scattered at individual use sites.
`DEPLOYMENT_MODE` (`development` / `test` / `controlled_pilot`) gates which
invariants apply; stricter secret, API-key, and CORS requirements are only
enforced in `controlled_pilot`.

## Commit and PR conventions

None specified beyond what `git log` shows for this repo. Follow the
existing commit message style visible in history; no additional format is
mandated here.
