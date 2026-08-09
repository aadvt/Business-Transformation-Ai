# Sanjeevani — Backend (Phase 4a: agents + orchestrator)

FastAPI backend for Sanjeevani, a multi-agent supply-chain disruption system for
Indian mid-market manufacturers. Phase 2 added a real database (Neon Postgres)
behind the exact same API contract from Phase 1; Phase 3 wired the model layer
to watsonx.ai; **Phase 4a adds the three backend agents (Sentinel, Diagnosis,
Sourcing) and an explicit orchestrator state machine that actually run the
disruption pipeline.** See `CLAUDE.md` for locked conventions (including the
governing principle: the LLM never produces a number that reaches the user —
see `app/services/exposure.py`) and `CONTRACT.md` for the full endpoint +
WebSocket reference (still unchanged from Phase 1 for every stable endpoint).

## Try it in one command

```bash
python -m app.seed --reset   # if you haven't already
uvicorn app.main:app --reload

curl -X POST localhost:8000/api/v1/disruptions/simulate \
  -H 'Content-Type: application/json' -d '{"scenario":"delivery_delay_castings"}'
curl -s localhost:8000/api/v1/disruptions/<id-from-above> | python -m json.tool
```

This runs Sentinel (detects the seeded overdue PO), Diagnosis (computes real
exposure and gets a Guardian-checked narrative), and Sourcing (ranks and
verifies alternate vendors) end to end, stopping at `AWAITING_APPROVAL` — the
mandatory human gate. Expect ~30-90s: several real watsonx calls happen in
sequence. See `app/agents/`.

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
# stop any running uvicorn first — see the note below
python -m app.seed --reset
```

**Stop the server before running `--reset`.** It drops and recreates every
table, which needs a lock the running app's connection pool (and the
background Sentinel loop) will be holding — you'll hit a real
`psycopg.errors.DeadlockDetected` otherwise.

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
| `/forecast/{sku}` | **Real TTM model** — zero-shot Granite TinyTimeMixer forecast over seeded inventory history; falls back to linear-trend extrapolation if TTM isn't loaded (see below) |
| Sentinel's TTM stockout-risk detector | **Real** — additive detector, same model as above, feeds real disruptions with `detector_source=TTM_FORECAST` |
| Audit log | **Real** — append-only, hash-chained, `verify_audit_chain()` catches tampering |
| WebSocket `/api/v1/live` | **Real** connection + ring buffer + heartbeat; **scripted** event content in mock mode |
| Idempotency on POST endpoints | **Real** — same `idempotency_key` always returns the identical cached response |
| Agent/LLM logic (diagnosis, sourcing, negotiation reasoning) | **Not implemented** — seeded data represents plausible agent output |

## IBM integration status

Tracked live at `GET /api/v1/metrics/demo` → `integrations`, and mirrored here so
anyone opening this repo mid-hackathon knows what to trust without hitting the API:

| Integration | Status | Notes |
|---|---|---|
| watsonx.ai (LLM reasoning) | **LIVE** | Real `ibm/granite-4-h-small` calls via `app/llm/`, IAM token exchange cached, ~0.6–2.7s typical latency. Verify with `python scripts/smoke_llm.py`. Degrades to StubLLM on failure rather than erroring. |
| Granite Guardian (AI safety) | **STUB — surrogate mode** | The gate is live and discriminating, but **no `granite-guardian-*` model is available on this account's region/plan** (verified: `eu-de` `foundation_model_specs` lists 15 models, none of them Guardian). Risk scoring currently runs Guardian's risk definitions through `granite-4-h-small` instead. Every verdict carries `mode=LLM_SURROGATE` and `is_real_guardian=False`. **Do not present this as Granite Guardian.** Flips to real automatically if a Guardian model becomes available. |
| Supermemory (vendor memory) | **STUB** | `memory_source` field models the concept; no real memory store wired |
| Verification (GSTIN/Udyam checks) | **STUB (real offline logic)** | `app/services/gstin.py` does real structural+checksum validation; does not call the live GST portal |
| TTM (Granite time-series forecasting) | **LIVE** | `ibm-granite/granite-timeseries-ttm-r2` runs a real zero-shot forecast (96-step horizon) over seeded `inventory_snapshots`, both as a Sentinel detector (`app/agents/detectors/ttm_forecast.py`) and behind `GET /forecast/{sku}`. Falls back to linear-trend extrapolation (`model="RULE_BASED"`) if the model isn't loaded — never 500s. Verify with `python scripts/smoke_ttm.py`. |
| Orchestrate | **NOT YET WIRED** | No integration point exists yet |
| Neon Postgres | **LIVE** | Pooled connection for app traffic, direct connection for seed/schema — see `CLAUDE.md` |

**LIVE** means calling a real IBM/external service (or, for Neon, a real
database). Update this table (and `metrics_demo.json`) as each remaining
integration goes from STUB → LIVE.

### Checking the IBM wiring

```bash
python scripts/smoke_llm.py
# configured provider : auto
# watsonx configured  : True
# model: ibm/granite-4-h-small | provider: WATSONX | 780ms | parsed OK
# watsonx.ai is LIVE.

python scripts/smoke_guardian.py
# groundedness: PASS   [clean]
# groundedness: FAIL   [ungrounded]
```

Both exit non-zero if the live call fails or degrades, so they work as a
pre-demo check. `smoke_llm.py` exits 1 if the answer came from the stub.

```bash
python scripts/smoke_ttm.py
# sku: CRS-2MM | model: granite-timeseries-ttm-r2 | forecast crosses reorder point in 1 hours | 15ms
# TTM is LIVE.

curl -X POST localhost:8000/api/v1/disruptions/simulate -d '{"scenario":"stockout_risk"}'
curl -s localhost:8000/api/v1/disruptions/<id> | python -m json.tool
# "detector_source": "TTM_FORECAST"  <- confirms this specific alert came from
#                                        IBM's time-series model, not a rule
```

Model weights (`ibm-granite/granite-timeseries-ttm-r2`) must be present in the
Hugging Face Hub cache (`~/.cache/huggingface/hub`) — pre-cached from Phase 0
in this environment. `ENABLE_TTM_DETECTOR=false` disables the detector
instantly (no redeploy) if it ever misbehaves close to demo time; `/forecast`
degrades to `RULE_BASED` automatically either way.

## The model layer (`app/llm/`)

Every agent goes through `LLMClient` — no agent ever calls an HTTP model
endpoint directly.

```python
from app.llm import get_llm, prompts

llm = get_llm()
result = llm.complete(
    prompts.DIAGNOSIS_NARRATIVE_V1,   # never an inline prompt string
    user_payload,
    schema=MyPydanticModel,           # structured output, parsed + validated
    tag=prompts.TAG_DIAGNOSIS_NARRATIVE,
    disruption_id=disruption.id,      # optional; links the agent_runs row
)
result.parsed        # MyPydanticModel instance, never a raw string
result.provider      # "WATSONX" | "STUB"
result.degraded      # True if watsonx failed and the stub answered
```

What it guarantees:

- **Structured output or an exception.** `schema=` appends the model's JSON
  Schema to the system prompt, strips markdown fences, salvages a bare `{...}`
  from surrounding prose, and on failure does exactly **one** repair round-trip
  feeding the parse error back. If that also fails it raises `LLMSchemaError` —
  a raw model string never reaches the database.
- **The demo never dies.** watsonx failures retry 3× with exponential backoff
  (only on timeouts/5xx/429 — a 400 is our bug and won't get better), then
  degrade to `StubLLM` with a loud log and an `agent_runs` error row.
- **Everything is observable.** Every LLM and Guardian call writes an
  `agent_runs` row (tag, model id, latency, token usage, 500-char input/output
  summaries, error). All logs are single-line JSON carrying a correlation id
  that follows an inbound `X-Correlation-ID` header.
- **Provider selection**: `LLM_PROVIDER=stub` or missing credentials → StubLLM,
  no network. This is what the test suite uses.

`app/llm/transport.py` is the only file that knows watsonx's wire format —
swapping to the official `ibm-watsonx-ai` SDK is a one-file change. We use raw
`httpx` because the SDK pulls pandas, numpy and the IBM COS/S3 SDK (~25MB of
transitive dependencies) to do what is, for us, two POST requests.

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
