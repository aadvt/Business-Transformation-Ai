# Sanjeevani backend — locked decisions

This file records decisions made across phases so future sessions don't
re-litigate them. Read this before changing conventions.

## Phase

**Phase 4b: TTM (Granite TinyTimeMixer) stockout-risk detection is live.**
See "TTM detector" below. Phase 4a's agents/orchestrator remain in force.

**Phase 4a: the three backend agents (Sentinel, Diagnosis, Sourcing) and the
orchestrator are live.** See "Agents" and "Orchestrator" below. Phases 2/3's
notes remain in force.

**Phase 3: the model layer is live.** See "Model layer" below. Phase 2's
persistence notes remain in force.

**Phase 2: real persistence.** The database is Neon
Postgres, reached via SQLAlchemy 2.0 (sync engine, psycopg v3 driver), or
sqlite as an offline fallback (see "Two databases" below). No Alembic —
`Base.metadata.create_all` plus an idempotent seed script (`app/seed.py`).

The Phase 1 JSON-fixture mock store (`app/mocks/loader.py`) still exists and
still works — it's the `USE_MOCKS=true` fallback. **The API shapes did not
change between phases.** Every router now has two code paths (mock store vs.
repository-backed DB query) gated on `settings.use_mocks`, and
`tests/test_contract.py` passes against both. Do not remove the mock path;
it's the documented emergency fallback if Postgres is unreachable.

Still not present after Phase 3: the agents themselves (nothing calls the model
layer in the request path yet), Supermemory, Orchestrate, and the TTM model.
`/forecast/{sku}` and `/vendors/{id}/context` are real DB queries, but their
"intelligence" is still rule-based — see README's integration status table.

## Model layer (Phase 3) — `app/llm/`

**Every agent goes through `LLMClient`. No agent ever calls an HTTP model
endpoint directly.** If you find yourself importing `httpx` in an agent, stop.

- `app/llm/client.py` — `LLMClient` ABC + `WatsonxLLM` + `StubLLM` + `get_llm()`.
  Subclasses implement exactly one primitive, `_generate(system, user,
  max_tokens, temperature, tag)`. Everything that must behave identically across
  providers (schema injection, fence stripping, the repair round-trip,
  `agent_runs` recording) lives on the base class so the two implementations
  cannot drift.
- `app/llm/transport.py` — the ONLY file that knows watsonx's wire format (IAM
  token exchange + cache, `/ml/v1/text/chat`, `/ml/v1/text/generation`, retry
  policy). Swapping to the official SDK is a one-file change; that boundary is
  the whole point of the module, don't leak wire details past it. We use raw
  httpx deliberately — the SDK drags in pandas/numpy/COS-SDK for two POSTs.
- `app/llm/prompts.py` — **every** system prompt, named and versioned. No
  inline prompt strings anywhere else, no exceptions. Never edit a `_V1` in
  place once an agent depends on it; add `_V2` and switch the caller.
- `app/llm/guardian.py` — risk scoring, see below.
- `app/llm/runs.py` — `agent_runs` recording, fail-soft by design.

### Rules that are load-bearing

- **A raw model string must never reach the database.** Call with `schema=` and
  use `result.parsed`. On unparseable output the client does ONE repair
  round-trip (feeding the parse error back) and then raises `LLMSchemaError` —
  it never returns half-valid data. Callers decide the fallback.
- **Degrade, never crash.** `WatsonxLLM` retries 3× with exponential backoff on
  timeouts/5xx/429 only (a 400 is our bug and won't improve), then falls back to
  `StubLLM`, logs loudly, and writes an error `agent_runs` row. The returned
  `LLMResult` reports `provider="STUB"` and `degraded=True` so callers and the
  audit trail can always tell what actually answered. Don't add a code path that
  lets a model failure raise into a request handler.
- **Stub responses are real prose, not placeholders.** `app/llm/stub_responses.py`
  is what the system says during a degraded demo. Keep new entries realistic and
  schema-valid — `tests/test_llm.py` asserts every canned response parses.
- **Tags are ≤30 chars** (the `agent_runs.agent` column width) and defined in
  `prompts.py` as `TAG_*` constants. A test enforces this.

### Guardian: two modes, and why

`GuardianVerdict.status` is `OK` | `UNAVAILABLE`; `GuardianVerdict.mode` is
`GRANITE_GUARDIAN` | `LLM_SURROGATE` | `NONE`.

- **`passed=True` with `status=UNAVAILABLE` is NOT an approval.** It exists so a
  non-enforcing caller doesn't block the pipeline. Enforcing callers (Phase 6's
  negotiation write-back) must check `verdict.needs_human_review`, never bare
  `passed`.
- **`mode=LLM_SURROGATE` is not Granite Guardian.** No `granite-guardian-*`
  model is available on our current account/region (eu-de exposes 15 models,
  none of them Guardian), so the gate falls back to running Guardian's risk
  definitions through `granite-4-h-small`. It discriminates correctly (verified
  by `scripts/smoke_guardian.py`) and keeps the safety gate functional, but
  anything that reports provenance to a user or a judge must check
  `verdict.is_real_guardian`. Never describe surrogate output as Granite
  Guardian in a UI, a pitch, or a README.
- Mode is resolved lazily and cached process-wide, so a missing Guardian model
  costs one 404, not one per call. A genuine outage (not `model_not_supported`)
  stays `UNAVAILABLE` rather than silently downgrading the safety layer.

### Observability

Every LLM and Guardian call writes an `agent_runs` row (tag, model id, latency,
token usage, 500-char truncated input/output summaries, error). Recording is
fail-soft — a DB problem degrades to a log line, because observability must
never be why a demo call fails. Logs are single-line JSON via
`app/observability.py`, carrying a correlation id set per request from an
inbound `X-Correlation-ID` (or generated). Use `extra={...}` for structured
fields rather than f-stringing values into the message.

### Secrets

watsonx credentials live in `.env` only (gitignored). `.env.example` carries
empty placeholders and comments. Never log the API key or an IAM token — the
transport deliberately logs IAM failures by status code only, because IBM's
error envelope can echo the request back.

## Two databases: pooled vs. direct

- `DATABASE_URL` (pooled, hostname has `-pooler`) — used by the running app
  for **all** request traffic. Tuned with `pool_size=5, max_overflow=5,
  pool_recycle=300, pool_pre_ping=True`.
- `DATABASE_URL_DIRECT` (non-pooled) — used **only** by `app/seed.py` /
  `create_all`. Never point request traffic at this one.
- Both also accept a `sqlite:///...` URL — every model in `app/db/models.py`
  uses only portable column types (String, JSON, BigInteger, Boolean,
  DateTime(timezone=True)) so the schema is identical on either backend. This
  is the offline fallback if venue wifi blocks outbound Postgres (port 5432):
  set `DATABASE_URL=sqlite:///./sanjeevani.db`, drop `DATABASE_URL_DIRECT`,
  reseed, done. See README.
- **sqlite silently drops tzinfo on read-back** (`DateTime(timezone=True)` has
  no native sqlite equivalent). Every datetime this app writes is UTC by
  convention, so `app.schemas.money.as_utc()` / `to_iso()` reattach UTC to a
  naive value read back from sqlite. Use `to_iso(dt)` — never
  `dt.isoformat()` — anywhere a DB-sourced datetime becomes a response field
  or an audit-hash input, or sqlite and Postgres will silently disagree. This
  bug was real and caught by hand during Phase 2 development (broke the audit
  hash chain on sqlite) — don't reintroduce it.

## ORM models have no `relationship()`s — flush parents before children

Every FK is a plain `String` column plus a `ForeignKey` constraint, not an ORM
`relationship()`. That means **SQLAlchemy's unit-of-work does NOT auto-order
cross-table inserts by FK dependency** — that ordering only kicks in via
declared relationships. sqlite (default mode) doesn't enforce FK constraints
so this bug is invisible there; Postgres enforces them and will reject the
insert. Rule: when seeding or writing code that inserts a parent row and
then a child row referencing it by plain id column in the same unit of work,
call `session.flush()` after the parent `add()` before adding children. See
the `session.flush()` calls scattered through `app/seed.py` right after each
`Organisation`/`DisruptionEvent`/`SettlementBatchRow` — that pattern is
required, not decorative.

## Conventions (still true, apply everywhere)

- **Money**: integer paise, `_paise` suffix, never float. `format_inr()` /
  `format_inr_short()` in `app/schemas/money.py`. Never hand-write a
  `_display` string — always derive it from the paise value. Fixture/seed
  consistency is checked by `tests/test_money.py`.
- **Timestamps**: UTC ISO-8601, `_at` suffix. Use `to_iso(dt)` for any
  DB-sourced datetime (see sqlite tzinfo note above), `utc_now_iso()` for a
  fresh one.
- **IDs**: string UUIDv4 everywhere, including seeded data — see
  `app.services.ids.det_uuid4` for how the seed script gets *reproducible*
  UUIDv4-shaped ids (stamps version/variant bits onto a seeded RNG's bytes).
- **Envelopes**: every domain object response includes `id`, `created_at`,
  `updated_at`.
- **Enums**: UPPER_SNAKE, defined once in `app/schemas/enums.py`. Stored as
  plain `String` columns in the DB (not native Postgres ENUM types) for the
  same sqlite-portability reason as everything else — validated against the
  Python enum at the repository layer, not the DB schema layer.

## Idempotency — two different mechanisms, both required

- `approvals` has its own `idempotency_key` column: at most one decision is
  ever recorded per approval, so "replay same key → same row" is just "if
  `approval.idempotency_key == key`, don't mutate, return current state."
- Settlement execute/confirm and negotiation-outcome have no natural
  "already happened" marker on their own row, so they use a generic
  `idempotency_records` table (`app/repositories/_idempotency.py`,
  `idempotent(session, key, endpoint, compute_fn)`). This table is a Phase 2
  addition beyond the literal table list in the original brief — it exists
  because the contract's idempotency guarantee has to hold regardless.
- **Both mechanisms must report `is_replay` back to the router**, because the
  router only fires the WS broadcast on a *fresh* decision, never on a
  replay (this matches Phase 1 behavior exactly — check before "simplifying"
  this away). `repo.decide_approval`, `repo.execute_batch`,
  `repo.confirm_batch`, and `repo.post_outcome` all return
  `(response, is_replay)` tuples for this reason.

## Audit log is append-only and hash-chained

`app.services.audit.append_audit(...)` is the **only** write path to
`audit_log` — never construct `AuditLogEntry` directly anywhere else,
including in new repository code. Each row's `hash` commits to
`prev_hash + canonical_json(row)`; chains are scoped per-disruption (or
per-org for `disruption_id=None` system entries). `verify_audit_chain(session,
disruption_id)` recomputes and checks the whole chain. This is the stand-in
for watsonx.governance's audit trail — treat it as load-bearing, not
decorative logging.

## Seed script (`python -m app.seed --reset`)

- Deterministic: one `random.Random(SEED)` instance, drawn from in a fixed
  order, so `--reset` always produces byte-identical data. Never call
  `random`/`uuid.uuid4()` directly for seed data — use the shared `rng` and
  `det_uuid4(rng)`.
- Idempotent: no `--reset` + organisation already exists → no-op.
- Five vendors and three disruptions keep the **exact UUIDs from the Phase 1
  mock fixtures** (`V1_ID`..`V5_ID`, `D1_ID`..`D3_ID`, plus the approval/
  negotiation/settlement-batch ids `tests/test_contract.py` references) —
  this is what makes "the contract test suite still passes against the real
  database" true. If you ever need to change one of these ids, update
  `tests/test_contract.py` in the same commit.
- The two golden-path scenarios (delivery-delay, stockout-risk) are seeded as
  raw substrate (a PO, an inventory trend) with **no** `disruption_events`
  row — they're meant to be caught by Phase 3's Sentinel, not pre-solved.

## Repository layer

- `app/repositories/` — one module per aggregate, mirrors `app/routers/`.
  Routers call repositories, never the ORM directly, and vice versa:
  repositories never import FastAPI.
- Some CONTRACT.md fields aren't backed by their own table (vendor context's
  `guardrails`/`briefing`/`history_summary`, forecast's trend) — those are
  computed at query time from the tables that do exist. `agents/status` and
  `metrics/demo` remain fixture-backed even with `USE_MOCKS=false` (no table
  was specified for live agent status or demo metrics in the Phase 2 brief;
  that's Phase 3+ territory).
- `--use-mocks` / `USE_MOCKS=true`: every DB-backed router keeps its original
  Phase 1 mock-store code path alongside the new repository call, branching
  on `settings.use_mocks`. Keep both paths when adding new DB-backed
  endpoints — don't delete the mock path "for cleanliness."

## API shape rules (Phase 1, still true)

- Every response model lives in `app/schemas/`, split by domain.
- Every router file maps to one domain and is included in `app/main.py`.
- Auth: `X-API-Key` header, checked only when `REQUIRE_API_KEY=true`.
- Path spelling is intentionally inconsistent between `/api/v1/settlements/...`
  (plural, execute) and `/api/v1/settlement/...` (singular, batch/confirm) —
  matches the locked contract in `CONTRACT.md` exactly, don't "fix" it.

## WebSocket `/api/v1/live`

- Single global `LiveFeedManager` (`app/ws_manager.py`), 50-event ring buffer,
  replayed on connect. `HEARTBEAT` every 20s. Scripted disruption replay every
  45s when `MOCK_LIVE_REPLAY=true` — its target disruption id
  (`228bdcbe-3b9e-42a4-a84f-2f42c48ec664`) is the same D3 now seeded for real,
  so this still lines up.
- Router-triggered broadcasts (`APPROVAL_DECIDED`, `SETTLEMENT_STAGED`,
  `NEGOTIATION_UPDATE`) only fire on a fresh mutation, never on an idempotent
  replay — see "Idempotency" above.

## Cold-start resilience

- `app/db/session.check_connectivity()` runs one blocking `SELECT 1` at
  startup and logs the round-trip; a cold Neon compute shows up as a multi-
  second log line instead of silently costing the first real request.
- `app/db/keepalive.py` runs a daemon thread doing `SELECT 1` every 4 minutes
  (inside Neon's ~5 minute scale-to-zero window) for the life of the process.
  Started/stopped in `app/main.py`'s lifespan hook, skipped entirely when
  `USE_MOCKS=true`.

## Governing principle for agents (non-negotiable)

**The LLM never produces a number that reaches the user.** All financial
arithmetic is deterministic Python in `app/services/exposure.py` — pure
functions, no DB, no I/O, fully unit-tested (`tests/test_exposure.py`). The
LLM classifies into enums and writes prose explaining numbers Python already
computed. If a judge asks "how did you get ₹6.2 lakh", open
`app/services/exposure.py` and the `exposure_calcs.inputs` JSON column — that
row is the arithmetic's defence, not a log line.

## Agents (`app/agents/`)

- `base.py` — `Agent` ABC. `run(ctx)` wraps every agent's `_execute(ctx)`:
  times it, writes one `agent_runs` row (agent=self.name — a coarser trace
  than the fine-grained rows the agent's own `llm.complete()`/`guardian.check()`
  calls write under their own tags), writes one `audit_log` entry via
  `append_audit`, and **never lets an exception escape** — a crash becomes
  `AgentResult(status=ERROR, error=...)` after rolling back the session, so a
  broken agent degrades the pipeline instead of 500ing the API.
- **Agents never touch `disruption.stage`.** Only `app.orchestrator.engine.transition()`
  does. This is what makes the state machine provably the sole authority — see
  "Orchestrator" below. If you're tempted to set `.stage` inside an agent,
  don't; call `transition()` from the orchestrator/pipeline layer instead.
- `sentinel.py` — deterministic detectors run FIRST (`overdue_delivery`,
  `vendor_silence`, `quality_spike`, `price_shock`, each a pure
  `(session, org_id) -> list[Signal]` function), THEN one LLM call classifies
  each new signal into a `DisruptionType` + 90-char headline. Dedup is by
  `(vendor_id, detector_name)` against already-open disruptions, so the 30s
  scheduler tick doesn't re-raise the same thing forever. `DETECTORS` is a
  plain module-level list — Phase 4b appends its TTM stockout-risk detector to
  it without editing this file. If the LLM classification fails schema twice,
  Sentinel falls back to a deterministic detector→type mapping
  (`_FALLBACK_TYPE_BY_DETECTOR`) rather than dropping the signal.
- **Every call into `Agent.run()` from async code MUST go through
  `asyncio.to_thread()`.** Agents are fully synchronous (sync SQLAlchemy
  session, blocking httpx calls to watsonx) and a single classification round
  can take several seconds; calling one directly from an `async def` (the
  background Sentinel loop, `run_pipeline_to_awaiting_approval`, the simulate
  router) stalls the entire event loop — and therefore every other request
  the server is handling — for that whole span. This was a real bug found by
  hand: a single `POST /disruptions/simulate` call made `GET /health` hang for
  a minute on the same server. `run_sentinel_loop`, `pipeline.py`, and
  `simulate.py` all wrap their agent calls in `asyncio.to_thread`; a bare
  `agent.run(ctx)` call inside any `async def` is a regression.
- `diagnosis.py` — computes exposure via `compute_exposure()`, then ONE LLM
  call for `{root_cause, narrative (<=280 chars), evidence}`. **Guardian
  checkpoint #1**: narrative groundedness is checked against the same evidence
  it was built from. Ungrounded once → regenerate once. Ungrounded twice (or
  the LLM call itself fails schema validation, which can happen independently
  of groundedness — Granite doesn't always respect a 280-char JSON Schema
  `maxLength`) → fall back to `_template_narrative()`, built by plain string
  formatting from the exposure breakdown, and mark
  `diagnosis_narrative_source="TEMPLATE"`. Both failure modes route to the
  same fallback for the same reason: never let a narrative-generation problem
  crash the disruption. `production_critical`/`consumption_rate_known` are
  derived from whether the affected SKU appears in `inventory_snapshots` —
  we only claim idle-line cost when we actually track that SKU's consumption,
  never as a guess (`_is_production_critical`).
- `sourcing.py` — queries same-category vendors excluding the failed one
  (not filtered to `is_backup_pool=True` — Phase 2's own D1 fixture uses a
  primary vendor as an alternate, so "the pool to source from" is broader than
  that flag). Scoring is a deterministic weighted sum (weights in
  `settings.sourcing_weight_*`, must sum to 1.0 — enforced by a test) with
  each component (`reliability`, `lead_time`, `price`, `geography` via
  haversine distance to the org's plant lat/lng, `relationship`) logged to
  `audit_log` per candidate so it's explainable. The LLM writes ONE batched
  rationale per already-ranked top-3 candidates — it never sees the score and
  cannot change the ranking. `quoted_unit_price_paise`/`quoted_lead_time_days`
  per candidate are estimates from the vendor's own historical PO data (their
  actual average price/lead-time), not a live quote — Negotiation (Phase 6)
  firms these up. After candidates are persisted, exposure is recomputed with
  the top candidate as `best_backup_quote` (fills in `expedite_premium`) and a
  NEW `exposure_calcs` row is inserted — `repositories/disruptions.py` already
  reads the most-recent-by-`computed_at` row, so this supersedes the earlier
  one for API responses while keeping history.

## Orchestrator (`app/orchestrator/`)

- `engine.py` — `ALLOWED_TRANSITIONS: dict[stage, set[stage]]` +
  `transition(session, org_id, disruption, to_stage, actor_type, actor, note=None)`.
  This is the ONLY place `disruption.stage` may change, and it's illegal to
  bypass: `transition()` raises `IllegalTransitionError` on an unlisted
  (from, to) pair, stamps whichever `*_at` column(s) `TIMESTAMP_COLUMNS` maps
  the transition to, writes one `append_audit` entry, and commits.
- **The human gate is structural, not conventional.** `HUMAN_ONLY_TRANSITIONS`
  = `{(AWAITING_APPROVAL,APPROVED), (AWAITING_APPROVAL,REJECTED),
  (AWAITING_APPROVAL,SOURCING), (SETTLEMENT_PENDING,SETTLED)}` — `transition()`
  raises if `actor_type != "HUMAN"` on any of these, and `NEGOTIATING` has
  exactly one legal predecessor (`APPROVED`), so nothing can reach it without
  first passing the approval endpoint. `tests/test_state_machine.py` asserts
  both the raise behaviour and the structural single-predecessor property —
  don't weaken either without updating that test *and* understanding why it
  existed.
- `repositories/approvals.py` and `repositories/negotiations.py` route their
  stage changes through `transition()` (they used to mutate `.stage` directly
  before Phase 4a — if you ever see `disruption.stage = ...` written anywhere
  outside `engine.py`, that's a regression, fix it).
- `pipeline.py` — `run_pipeline_to_awaiting_approval(org_id, disruption_id)`
  drives DETECTED→DIAGNOSED→SOURCING→AWAITING_APPROVAL (Diagnosis, then
  Sourcing, with a `transition()` + WS broadcast between each step), creating
  the `Approval` row itself before the final transition. Stops at
  AWAITING_APPROVAL on purpose — everything past that needs the human gate.
  On any agent failure, transitions to FAILED instead of leaving the
  disruption stuck implying work is still happening.
- `POST /api/v1/disruptions/simulate` (`app/routers/simulate.py`) — dev-only,
  gated on `settings.demo_mode` (404s when off). Maps a scenario name to a
  seeded vendor (`SCENARIOS` dict — only `delivery_delay_castings` is wired
  in Phase 4a; stockout-risk needs Phase 4b's TTM detector), runs Sentinel
  once to pick up that vendor's golden-path signal, then runs the pipeline.
  Idempotent-ish: calling it again on an already-progressed disruption just
  reports its current stage rather than re-running the pipeline.

## TTM detector (Phase 4b) — `app/agents/detectors/ttm_forecast.py`

- **Purely additive to Phase 4a's Sentinel.** `sentinel.py` was not edited —
  `ttm_forecast.py` imports `app.agents.sentinel` and appends
  `stockout_risk_ttm` to the shared `DETECTORS` list as a module-level import
  side effect. This only actually runs if something imports
  `app.agents.detectors.ttm_forecast` — that import lives in `app/main.py`,
  right next to the `start_background_load()` call. If you ever move or
  remove that import, the detector silently stops being registered even
  though the module still "exists" — check `app/main.py` first if TTM signals
  stop appearing.
- **Model loads once, on a worker thread, at startup — never per-request,
  never blocking startup.** `start_background_load()` does
  `asyncio.create_task(asyncio.to_thread(load_model))` and returns
  immediately; the app accepts requests before the model finishes loading.
  `TTM_AVAILABLE` (module global) is the single source of truth for "is it
  ready" — `stockout_risk_ttm()` and `GET /forecast/{sku}` both check it and
  degrade to nothing/`RULE_BASED` respectively rather than erroring.
  `ENABLE_TTM_DETECTOR=false` is the instant kill switch (checked first, no
  network/import cost either way).
- **No formal SKU → supplying-vendor table exists.** `inventory_snapshots`
  has no `vendor_id` column, but `Signal`/`DisruptionEvent` both require one.
  `SKU_VENDOR_HINTS` is a hardcoded, documented mapping (kept in sync with
  `app/seed.py`'s `INVENTORY_SKUS` and vendor list) used only to attribute a
  stockout-risk signal to a vendor. If a SKU isn't in the map, the signal is
  dropped with a logged warning rather than guessing or crashing. A real
  vendor-SKU relationship table is the correct fix whenever Phase 5+ needs
  this to generalize past the 10 seeded SKUs.
- **Crossing detection is one pure function** — `find_projected_breach(forecast,
  reorder_point)` — deliberately factored out of `run_forecast()` so it's
  unit-testable with zero model, zero network, zero DB. It returns the first
  forecast step at-or-below `reorder_point`; if the current on-hand value is
  already below it (true for the seeded CRS-2MM series — see below), that's
  index 0, an immediate breach, which is correct, not a bug.
- **Exposure is honestly zero for TTM-only signals.** A stockout-risk signal
  has no `affected_po_ids` (there's no PO to point at — the risk is about a
  *future* order), so `compute_exposure()` correctly returns
  `total_paise=0, confidence=0.0` for it: blocked_value and penalty both need
  a PO, and neither exists yet. Same reasoning as always — the exposure
  engine only reports what it can actually justify from data, never a filled-
  in guess. If the pitch needs a nonzero number for this scenario, that's a
  Diagnosis-agent enhancement (e.g. projected_shortfall × unit_price), not
  something to fake here.
- Golden path: `app/seed.py`'s CRS-2MM inventory series is a declining
  ("ramp") trend that's already below `reorder_point` by "now" — this is
  intentional (see Phase 2's seed notes), so TTM's forecast should show an
  immediate/near-immediate breach for it. `POST /disruptions/simulate` with
  `{"scenario": "stockout_risk"}` exercises this end to end; verify the
  resulting disruption's `detector_source` reads `TTM_FORECAST`, not
  `RULE_BASED` — that distinction is the whole point of this phase.
- Benchmarked like every other agent call: `_record_run()` writes an
  `agent_runs` row per SKU scanned (`agent="TTM_FORECAST_<sku>"`), with real
  inference latency, even though this isn't an LLM call — reuses
  `app.llm.runs.default_recorder()` rather than inventing a second mechanism.
- **Install is real and heavy** (torch + transformers, several minutes):
  `pip install "granite-tsfm[notebooks] @ git+https://github.com/ibm-granite/granite-tsfm.git"`.
  On Windows, cloning that repo can fail with `Filename too long` (deeply
  nested notebook fixtures) unless long paths are enabled for the clone —
  use a process-local override rather than touching global git config:
  `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.longpaths GIT_CONFIG_VALUE_0=true pip install ...`.
  Model weights (`ibm-granite/granite-timeseries-ttm-r2`) must be pre-cached
  in the Hugging Face Hub cache for this to work fully offline; a HEAD
  request to huggingface.co still fires even when cached (freshness check,
  not a re-download) — that's expected, not a bug.

## Schema drift note: `Vendor.lat`/`Vendor.lng`, `Organisation.lat`/`lng`

Added in Phase 4a for Sourcing's geographic-proximity score (and the
frontend's network map). Since there's no Alembic, `python -m app.seed --reset`
now does `Base.metadata.drop_all()` before `create_all()` — **`--reset` rebuilds
the schema from current `models.py`, not just row data.** This is deliberate:
it's the only way an added/changed column doesn't leave a stale table shape on
Neon. If you add a column, `--reset` is how it actually lands; a plain rerun
without `--reset` will not pick up a schema change.

**Stop the running app before `--reset`.** `DROP TABLE` needs an
`ACCESS EXCLUSIVE` lock; the running server's pooled connections (and the
background Sentinel loop, which queries every 30s) hold locks that collide
with it — hit this for real: `psycopg.errors.DeadlockDetected` on
`DROP TABLE audit_log`. Kill the uvicorn process first, reseed, then restart.

## Adding a new DB-backed endpoint

1. Table already exists? Add/extend the ORM model in `app/db/models.py`
   (portable types only) if not.
2. Response schema in `app/schemas/<domain>.py` (unchanged if the endpoint
   already existed in Phase 1).
3. Repository function in `app/repositories/<domain>.py` — session in,
   pydantic schema out. Call `append_audit` here for anything audit-worthy.
4. Router: add the `Depends(get_session)` + `settings.use_mocks` branch,
   keeping the existing mock path.
5. If it's new seed data, add it to `app/seed.py` (remember: flush parents
   before children — see above).
6. Update `CONTRACT.md` and add a case to `tests/test_contract.py` (and
   `tests/test_seed.py` if it's new seeded data).
