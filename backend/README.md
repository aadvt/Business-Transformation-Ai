# Sanjeevani — Backend (Phase 2: real persistence)

FastAPI backend for Sanjeevani, a multi-agent supply-chain disruption system for
Indian mid-market manufacturers. **Phase 2 adds a real database (Neon Postgres)
behind the exact same API contract from Phase 1** — no agent/LLM logic yet. See
`CLAUDE.md` for locked conventions and `CONTRACT.md` for the full endpoint +
WebSocket reference (unchanged from Phase 1 — that's the point).

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
```

Edit `.env`: paste your Neon **pooled** connection string into `DATABASE_URL`
and the **direct** (non-pooled) one into `DATABASE_URL_DIRECT` (get both from
the Neon console — paste verbatim, including `sslmode=require`). Or leave the
defaults as-is to run entirely offline against sqlite — see "Offline /
no-Postgres fallback" below.

```bash
python -m app.seed --reset      # creates tables + seeds demo data (idempotent)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# or: make dev
```

Then open:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

## Hitting the API

No auth is required by default (`REQUIRE_API_KEY=false`). Every endpoint below
now reads from the seeded database:

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
[`CONTRACT.md`](./CONTRACT.md) — unchanged from Phase 1.

## Seeding the database

```bash
python -m app.seed --reset
```

- **Deterministic**: fixed random seed — `--reset` always produces the same
  dataset (same vendor names, same PO history, same GSTINs).
- **Idempotent**: running it again *without* `--reset` is a no-op if data
  already exists.
- Seeds 1 organisation, 24 vendors (14 primary + 10 backup pool), ~140
  purchase orders (with realistic delivery variance — vendor `reliability_score`
  is *derived* from this history, not invented), ~7,200 inventory snapshot
  points across 10 SKUs (hourly × 30 days — clears IBM TinyTimeMixer's 512-point
  context window), WhatsApp-style comm events (including one vendor gone silent
  14 days ago), and two "golden path" scenarios seeded as raw data with no
  disruption row yet — ready for a future Sentinel agent to detect, not
  pre-solved. It prints a summary table + the two scenario ids when done.
- Five vendors and three disruptions keep the exact IDs from Phase 1's mock
  fixtures, so `tests/test_contract.py` passes unmodified against the real DB.

## Running tests

```bash
python -m app.seed --reset   # tests read live seeded state — reseed first
pytest -q
# or: make test
```

`tests/test_contract.py` hits every documented endpoint against the real
database and asserts 200 + basic schema shape — same file, same assertions as
Phase 1, now proven against Postgres instead of JSON fixtures. `tests/test_seed.py`
checks row counts, that every seeded vendor's GSTIN passes checksum validation,
that every SKU clears 512 inventory points, and that the audit hash chain
verifies for a seeded disruption. `tests/test_gstin.py` and `tests/test_money.py`
are pure unit tests (no DB needed).

Note: some contract tests mutate state (approvals, settlement confirmation) —
idempotent by `idempotency_key` within a single call, but running the full
suite twice in a row *will* leave e.g. vendor dues at zero the second time
(the settlement got confirmed on the first run). Reseed between test runs.

## Exporting the OpenAPI schema

```bash
python scripts/export_openapi.py
# writes openapi.json to the repo root
```

## Offline / no-Postgres fallback

Two independent fallbacks, for two different failure modes:

1. **No outbound Postgres (venue wifi blocks port 5432, or Neon is down):**
   set `DATABASE_URL=sqlite:///./sanjeevani.db` and drop
   `DATABASE_URL_DIRECT` (it falls back to `DATABASE_URL`), then
   `python -m app.seed --reset` and run normally. Every ORM model uses only
   portable column types, so the schema and all seeded data are identical —
   this is a real fallback, not a stub (see `tests/test_seed.py` passing
   against it).
2. **DB layer itself is broken and you just need the frontend/voice team
   unblocked immediately:** set `USE_MOCKS=true`. Every endpoint reverts to
   Phase 1's static JSON fixtures (`app/mocks/fixtures/`), same contract,
   zero DB dependency at all.

## What's real vs mocked

| Layer | State |
|---|---|
| HTTP routes, request/response schemas, status codes | **Real** — unchanged since Phase 1 |
| Vendors, disruptions, dashboard, approvals, settlements, audit, negotiations | **Real** — backed by Neon Postgres (or sqlite fallback) |
| `agents/status`, `metrics/demo` | **Mocked** — no table modeled for live agent status or demo metrics yet (Phase 3+) |
| GSTIN validation | **Real** (offline) — structural + mod-36 checksum validation, see `app/services/gstin.py`. Does not call the live GST portal. |
| `/forecast/{sku}` | **Real query, simple trend** — linear extrapolation over seeded inventory history; not the real TTM model (still STUB, see below) |
| Audit log | **Real** — append-only, hash-chained, `verify_audit_chain()` catches tampering |
| WebSocket `/api/v1/live` | **Real** connection + ring buffer + heartbeat; **scripted** event content in mock mode |
| Idempotency on POST endpoints | **Real** — same `idempotency_key` always returns the identical cached response |
| Agent/LLM logic (diagnosis, sourcing, negotiation reasoning) | **Not implemented** — seeded data represents plausible agent output |

## IBM integration status

Tracked live at `GET /api/v1/metrics/demo` → `integrations`, and mirrored here so
anyone opening this repo mid-hackathon knows what to trust without hitting the API:

| Integration | Status | Notes |
|---|---|---|
| watsonx (LLM reasoning) | **STUB** | Not called; seeded data stands in for agent output |
| Guardian (AI safety/guardrails) | **STUB** | `guardian: {status, passed}` fields are hand-authored in seed data |
| Supermemory (vendor memory) | **STUB** | `memory_source` field models the concept; no real memory store wired |
| Verification (GSTIN/Udyam checks) | **STUB (real offline logic)** | `app/services/gstin.py` does real structural+checksum validation; does not call the live GST portal |
| TTM (Granite time-series forecasting) | **STUB** | `/forecast/{sku}` does real linear-trend extrapolation over real seeded data, but not the actual granite-timeseries-ttm-r2 model — `model` field always reports `RULE_BASED` honestly |
| Orchestrate | **NOT YET WIRED** | No integration point exists yet |
| Neon Postgres | **LIVE** | Pooled connection for app traffic, direct connection for seed/schema — see `CLAUDE.md` |

**LIVE** means calling a real IBM/external service (or, for Neon, a real
database). Update this table (and `metrics_demo.json`) as each remaining
integration goes from STUB → LIVE.

## Auth

Set `REQUIRE_API_KEY=true` and `API_KEY=<your-key>` in `.env` to enforce the
`X-API-Key` header on every request. Off by default in dev.

## Project layout

```
app/
  main.py            FastAPI app, CORS, router registration, WS, lifespan, cold-start check
  config.py           pydantic-settings, reads .env
  constants.py         single-tenant org id shared by seed + repositories
  deps.py              shared dependencies (API key auth)
  ws_manager.py        WebSocket connection manager + ring buffer
  seed.py              deterministic, idempotent database seed script
  db/
    base.py             declarative base + portable column mixins
    models.py            all 16 ORM tables (see CLAUDE.md)
    session.py           pooled + direct engines, get_session dependency, connectivity check
    keepalive.py         background thread pinging Neon every 4 min
  services/
    gstin.py             offline GSTIN structural + checksum validation/generation
    audit.py              append-only, hash-chained audit log writer/verifier
    ids.py                deterministic UUIDv4 generator for seed data
  repositories/         one module per aggregate — session in, pydantic schema out
  schemas/             all pydantic request/response models, one file per domain
  routers/             one module per domain; each branches on settings.use_mocks
  mocks/
    fixtures/          JSON fixture files (the USE_MOCKS=true fallback "database")
    loader.py           loads + validates fixtures into an in-memory Store
    scripted_replay.py  background heartbeat + scripted WS event replay
tests/
  test_contract.py     hits every endpoint, asserts 200 + shape (real DB by default)
  test_seed.py          row counts, GSTIN validity, inventory point counts, audit chain
  test_gstin.py          GSTIN checksum unit tests
  test_money.py         paise/INR formatting + fixture consistency checks
scripts/
  export_openapi.py    writes openapi.json to the repo root
```
