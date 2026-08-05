# AI Analytics Workspace

An AI agent that ingests a structured dataset and a business question, then
autonomously executes the full Google Data Analytics lifecycle — **Ask →
Prepare → Process → Analyze → Share → Act** — producing a portfolio-grade
deliverable package while explicitly asking a human for anything it cannot
derive on its own.

Built as a dogfooding project: the founder is the primary user, validated
against a real 9,360-row retail dataset.

## Core Principle — "Ground or Ask"

The agent acts autonomously on anything it can derive from the data or
compute itself. It stops and asks the human for anything requiring outside
context it has no way to know (data provenance, licensing, stakeholder
identity, business intent). It never fabricates business context to appear
complete.

Proven in testing: the agent correctly refused to guess a dataset's source
or license, and separately resolved a data-integrity question itself
(a misleading "54% average discount" that turned out to be a bimodal
distribution, not organic markdown behavior) through statistical
investigation rather than asking or guessing.

## Architecture

```
Next.js frontend  <->  FastAPI API layer  <->  LangGraph agent orchestrator
                                                        |
                                    Postgres (state) + code execution sandbox
```

- **Agent orchestration:** LangGraph, chosen specifically for native
  human-in-the-loop interrupt support — checkpoints pause the graph,
  persist state, and resume exactly where they left off.
- **Backend:** Python + FastAPI.
- **Frontend:** Next.js 16 (App Router).
- **Database:** Postgres (Neon).
- **LLM provider:** Gemini (`gemini-2.5-flash-lite`, free tier), via a
  swappable single-function interface — not hardcoded to one provider.

## What's Built and Tested

All six agent nodes exist as real LangGraph nodes (not standalone scripts),
tested against a live Postgres database:

| Stage | Status |
|---|---|
| Prepare | Tested live — schema/quality profiling, real checkpoint pause/resume |
| Process | Tested live — cleaning checklist, data quality findings, derived metrics |
| Analyze | Tested live — 5 findings, distribution-shape check catches misleading averages |
| Share | Tested live — rule-based chart selection, headline + supporting visualizations |
| Act | Tested live — recommendations traced to finding IDs, mandatory limitations section |
| Ask | Built, uses a live Gemini call — not yet confirmed end-to-end (needs a live API key in a networked environment) |

FastAPI layer tested over real HTTP: `POST /sessions`, `POST
/sessions/{id}/resume`, `GET /sessions/{id}`.

Next.js frontend builds clean, implements upload → checkpoint card → live
pipeline tracker → report view.

## Running It

**Backend:**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your Postgres connection string + Gemini API key
python3 -m uvicorn app.api.main:app --reload
```

**Frontend** (separate terminal):
```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:3000`.

## Design Notes

- **Dataset-agnostic by design** — no hardcoded column names or business
  logic; schema is inferred at runtime.
- **Averages lie** — the Analyze stage checks distribution shape
  (bimodality, skew) before ever reporting a mean as representative.
- **Findings trace to recommendations** — every recommendation in Act cites
  the specific finding ID(s) behind it. No orphaned claims.
- **Cost constraint: $0** — the LLM provider is free-tier only, swappable
  via one config value.