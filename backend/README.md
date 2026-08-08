# Sanjeevani — Backend (contract-and-mocks phase)

FastAPI backend for Sanjeevani, a multi-agent supply-chain disruption system for
Indian mid-market manufacturers. **This phase is contract-and-mocks only** — every
endpoint returns realistic, validated fixture data. There is no database, no ORM,
and no real agent/LLM logic yet. See `CLAUDE.md` for the locked conventions this
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
cp .env.example .env          # defaults work out of the box, no editing required

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or: make dev
```

Then open:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

## Hitting the mock API

No auth is required by default (`REQUIRE_API_KEY=false` in `.env.example`). Every
endpoint below is live and returns fixture-backed data:

```bash
curl http://localhost:8000/api/v1/dashboard/summary
curl http://localhost:8000/api/v1/disruptions
curl http://localhost:8000/api/v1/disruptions/981f074f-9332-4b66-a24d-ffcaff0144cf
curl http://localhost:8000/api/v1/vendors/dues
curl http://localhost:8000/api/v1/vendors/4c34118b-bbe1-4016-885d-e6bc7917b3b0/context
```

WebSocket (use any WS client, e.g. `websocat` or the browser console):

```
ws://localhost:8000/api/v1/live
```

On connect you'll get the last 50 buffered events replayed, then a `HEARTBEAT`
every 20s. With `MOCK_LIVE_REPLAY=true` (default), a scripted disruption story
plays out over the feed every 45 seconds so there's always something moving.

Full request/response shapes, examples, and the WS event catalogue live in
[`CONTRACT.md`](./CONTRACT.md) — read that before wiring up frontend or voice-agent
calls.

## Running tests

```bash
pytest -q
# or: make test
```

`tests/test_contract.py` hits every documented endpoint and asserts a 200 plus
basic schema shape. `tests/test_money.py` unit-tests the paise → INR formatting
helpers, including lakh/crore grouping, and cross-checks every fixture's
`_display` string actually matches its `_paise` value (this caught a real bug
during development — keep these tests as fixtures grow).

## Exporting the OpenAPI schema

```bash
python scripts/export_openapi.py
# writes openapi.json to the repo root
```

## What's real vs mocked

| Layer | State |
|---|---|
| HTTP routes, request/response schemas, status codes | **Real** — this is the actual contract, not a placeholder |
| Fixture data (vendors, disruptions, forecasts, settlements, audit) | **Mocked** — realistic static JSON, validated at startup |
| WebSocket `/api/v1/live` | **Real** connection + ring buffer + heartbeat; **scripted** event content in mock mode |
| Idempotency on POST endpoints | **Real** — same `idempotency_key` always returns the identical cached response |
| Database / persistence across restarts | **Not implemented** — in-memory only, resets on restart |
| Agent logic (diagnosis, sourcing, negotiation, settlement) | **Not implemented** — fixtures represent plausible agent output |

## IBM integration status

Tracked live at `GET /api/v1/metrics/demo` → `integrations`, and mirrored here so
anyone opening this repo mid-hackathon knows what to trust without hitting the API:

| Integration | Status | Notes |
|---|---|---|
| watsonx (LLM reasoning) | **STUB** | Not called; fixture data stands in for agent output |
| Guardian (AI safety/guardrails) | **STUB** | `guardian: {status, passed}` fields are hand-authored in fixtures |
| Supermemory (vendor memory) | **STUB** | `memory_source` field models the concept; no real memory store wired |
| Verification (GSTIN/Udyam checks) | **STUB** | `verification` fields are fixture data, not a live GST portal call |
| TTM (Granite time-series forecasting) | **STUB** | `/forecast/{sku}` returns fixture curves; `model` field distinguishes TTM vs rule-based provenance for when it's wired |
| Orchestrate | **NOT YET WIRED** | No integration point exists yet |
| Neon Postgres | **NOT YET WIRED** | No database exists yet — see `CLAUDE.md` for the migration plan |

**LIVE** means calling a real IBM/external service. Nothing is LIVE in this phase —
update this table (and `metrics_demo.json`) as each integration goes from
STUB → LIVE.

## Auth

Set `REQUIRE_API_KEY=true` and `API_KEY=<your-key>` in `.env` to enforce the
`X-API-Key` header on every request. Off by default in dev.

## Project layout

```
app/
  main.py            FastAPI app, CORS, router registration, WS, lifespan
  config.py           pydantic-settings, reads .env
  deps.py              shared dependencies (API key auth)
  ws_manager.py        WebSocket connection manager + ring buffer
  schemas/            all pydantic request/response models, one file per domain
  routers/             one module per domain, mirrors schemas/
  mocks/
    fixtures/          JSON fixture files (the "database" for this phase)
    loader.py           loads + validates fixtures into an in-memory Store
    scripted_replay.py  background heartbeat + scripted WS event replay
tests/
  test_contract.py     hits every endpoint, asserts 200 + shape
  test_money.py         paise/INR formatting + fixture consistency checks
scripts/
  export_openapi.py    writes openapi.json to the repo root
```
