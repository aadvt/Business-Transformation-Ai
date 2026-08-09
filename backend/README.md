# Sanjeevani — Backend

FastAPI backend for Sanjeevani, a multi-agent supply-chain disruption system for
Indian mid-market manufacturers. **Postgres-backed** — vendors, disruptions,
settlements, negotiations, and audit history are real rows in a Neon database,
not fixture data. Two endpoints are still fixture-backed on purpose
(`/forecast/{sku}`, and part of `/vendors/{id}/context`) — see the table below
for exactly what's real vs not. See `CLAUDE.md` for the locked conventions this
codebase follows, and `CONTRACT.md` for the full endpoint + WebSocket reference.

## Quickstart

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# then set DATABASE_URL to a real Neon (or other Postgres) connection string —
# there is no in-memory fallback for the DB-backed endpoints

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or: make dev
```

Then open:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

## Hitting the API

No auth is required by default (`REQUIRE_API_KEY=false` in `.env.example`).
Every endpoint below queries the real database (use real ids from your own
`GET /api/v1/vendors` / `GET /api/v1/disruptions` — the ones below are
illustrative, not guaranteed to exist in every database):

```bash
curl http://localhost:8000/api/v1/dashboard/summary
curl http://localhost:8000/api/v1/disruptions
curl http://localhost:8000/api/v1/vendors/dues
```

WebSocket (use any WS client, e.g. `websocat` or the browser console):

```
ws://localhost:8000/api/v1/live
```

On connect you'll get the last 50 buffered events replayed, then a `HEARTBEAT`
every 20s. `MOCK_LIVE_REPLAY` defaults to **false** now that real data exists —
set it to `true` only for local UI-only work with no database configured, where
a scripted disruption story plays out over the feed every 45 seconds instead.

Full request/response shapes, examples, and the WS event catalogue live in
[`CONTRACT.md`](./CONTRACT.md) — read that before wiring up frontend or voice-agent
calls, including which fields are straight columns vs derived/reconstructed.

## Running tests

```bash
pytest -q
# or: make test
```

`tests/test_contract.py` and `tests/test_money.py` predate the move to Postgres
and still assert against the old fixture-specific values — expect failures
there until they're reworked against real data (tracked, not silently ignored).
`test_money.py`'s paise → INR formatting unit tests (no DB involved) still pass
and are still the right guardrail against `_paise`/`_display` drift.

## Exporting the OpenAPI schema

```bash
python scripts/export_openapi.py
# writes openapi.json to the repo root
```

## What's real vs mocked

| Layer | State |
|---|---|
| HTTP routes, request/response schemas, status codes | **Real** |
| Vendors, disruptions, settlements, negotiations, approvals, audit trail | **Real** — Neon Postgres, see `app/db_models.py` |
| `/forecast/{sku}` | **Mocked** — no forecast/projection data exists in the DB yet |
| `/vendors/{id}/context` guardrails/briefing/history_summary | **Mocked** — identity/reliability/last-terms are real, the narrative fields need real LLM summarization or business-policy config that doesn't exist as stored data |
| Agent execution (`agent_runs` table, backs `GET /agents/status`) | **Real table, no writer** — every agent reports IDLE until real agent execution logic exists |
| WebSocket `/api/v1/live` | **Real** connection + ring buffer + heartbeat; scripted event content only in opt-in mock mode |
| Idempotency on POST endpoints | **Real** — backed by the `idempotency_records` table, survives a process restart |
| Database / persistence across restarts | **Real** — Postgres, not in-memory |
| Agent *logic* (diagnosis, sourcing, negotiation, settlement decisions) | **Not implemented** — the data these produce is real when present, but nothing in this backend generates it |

## IBM integration status

Tracked live at `GET /api/v1/metrics/demo` → `integrations`, and mirrored here so
anyone opening this repo mid-hackathon knows what to trust without hitting the API:

| Integration | Status | Notes |
|---|---|---|
| watsonx (LLM reasoning) | **STUB** | Not called by this backend — real Granite calls exist in `../transaction-agent`, not here |
| Guardian (AI safety/guardrails) | **STUB** | `guardian: {status, passed}` fields are real DB columns, but nothing computes them live |
| Supermemory (vendor memory) | **STUB** | `memory_source` field models the concept; no real memory store wired |
| Verification (GSTIN/Udyam checks) | **STUB** | `verification` fields are real DB rows, not a live GST portal call |
| TTM (Granite time-series forecasting) | **STUB** | `/forecast/{sku}` returns fixture curves; `model` field distinguishes TTM vs rule-based provenance for when it's wired |
| Orchestrate | **NOT CONFIGURED** | No integration point exists yet |
| Neon Postgres | **LIVE** | This is the real database backing the endpoints above |

**LIVE** means calling a real IBM/external service, or in Neon's case, being the
real datastore. Update this table (and `app/routers/metrics.py`'s `integrations`
block) as each remaining integration goes from STUB → LIVE.

## Auth

Set `REQUIRE_API_KEY=true` and `API_KEY=<your-key>` in `.env` to enforce the
`X-API-Key` header on every request. Off by default in dev.

## Project layout

```
app/
  main.py            FastAPI app, CORS, router registration, WS, lifespan
  config.py           pydantic-settings, reads .env (DATABASE_URL, org_id, ...)
  db.py                async SQLAlchemy engine/session (see CLAUDE.md for the
                        PgBouncer prepared-statement caveat)
  db_models.py          SQLAlchemy models mirroring the real 16-table schema
  idempotency.py         DB-backed idempotency (idempotency_records table)
  deps.py              shared dependencies (API key auth)
  ws_manager.py        WebSocket connection manager + ring buffer
  transaction_agent_client.py  best-effort bridge to ../transaction-agent
  schemas/            all pydantic request/response models, one file per domain
  routers/             one module per domain, mirrors schemas/ — queries the DB
                        directly except forecast.py, which still reads fixtures
  mocks/
    fixtures/          forecasts.json + vendor_context.json only — everything
                        else moved to Postgres
    loader.py           loads + validates the two remaining fixture files
    scripted_replay.py  background heartbeat + opt-in scripted WS event replay
tests/
  test_contract.py     predates Postgres — needs rework, see "Running tests"
  test_money.py         paise/INR formatting unit tests still valid
scripts/
  export_openapi.py    writes openapi.json to the repo root
```
