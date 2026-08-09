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

## Demo phases (D0-D7)

Phases 1-4b (above) are the backend build. The demo layer on top is numbered
D0-D7 so it never collides with that numbering. Each demo phase gets recorded
here as it's completed, same style as the phase notes above.

### D0: dead code removed, demo enums, extended simulate, demo control plane

- Deleted `app/db.py`, `app/db_models.py`, `app/idempotency.py` — all three
  were unreachable dead code from an early async-store design that never
  shipped: `app/db/` (the package) shadows `app/db.py` (the module) in
  Python's import resolution, so every `from app.db import ...` anywhere in
  the codebase always resolved to the package, never the module, and nothing
  ever imported `app.db_models` or `app.idempotency` at all. Verified by
  grepping every import site and confirming `python -c "import app.db;
  print(app.db.__file__)"` prints `app/db/__init__.py`. Full test suite ran
  before and after — same pass/fail set, confirming the deletion changed
  nothing reachable. (Do not confuse this with `app/repositories/_idempotency.py`,
  which is live and documented above under "Idempotency".)
- New enums in `app/schemas/enums.py`: `GraphNodeKind`, `GraphNodeState`,
  `ScenarioKind`, `CallStatus`, `PlanChangeKind`, `IngestStatus`, plus 8 new
  `WSEventType` values (`IMPACT_COMPUTED`, `PLAN_PROPOSED`, `CALL_STARTED`,
  `CALL_TRANSCRIPT`, `CALL_FIELD_EXTRACTED`, `CALL_ENDED`, `INGEST_PROGRESS`,
  `BRIEFING_READY`). None of these have emitting/consuming code yet except
  `ScenarioKind` (see below) — they exist so the frontend can build against
  the WS payload shapes now; CONTRACT.md documents a sample payload for each.
  Whichever demo phase first emits one of the 8 new WS events should update
  CONTRACT.md's "emitting code doesn't exist yet" note for that event.
- `POST /api/v1/disruptions/simulate` gained a second, optional request
  shape: `{vendor_id, kind, effective_date}` alongside the original
  `{scenario}` shape, which is **unchanged and still the priority path** if
  `scenario` is present — see `app/routers/simulate.py`. The free-form path
  creates a `DisruptionEvent` directly (no Sentinel detector run) with
  `detector_name="demo_manual_trigger"` — a name that can never collide with
  a real detector's dedup check — and a deterministic (not LLM-generated)
  headline template per `ScenarioKind`, since the disruption type is already
  known from the kind→type mapping and there's no ambiguous signal for an
  LLM to classify. Both paths still run the same Diagnosis → Sourcing
  pipeline to `AWAITING_APPROVAL` through `asyncio.to_thread`, same as
  before.
- `GET /api/v1/simulate/targets` (new): lists seeded vendors with at least
  one open PO, sorted by an estimated exposure computed via the real
  `app.services.exposure.compute_exposure` (blocked value + penalty
  exposure only — no idle cost, no backup quote, since neither is known
  before a disruption exists). This is a *pre-trigger estimate* for
  populating the frontend's trigger modal, not a persisted `exposure_calcs`
  row — don't confuse the two if a number looks off.
- New demo control plane: `POST /api/v1/demo/reset` and `GET
  /api/v1/demo/state` in `app/routers/demo.py`. `/demo/reset` deliberately
  does NOT touch the schema — no `drop_all`/`create_all`, which CLAUDE.md's
  "Schema drift note" documents as deadlocking against a running server. It
  deletes rows from the disruption-lifecycle tables only (children before
  parents: `agent_runs`, `audit_log`, `vendor_candidates`, `verifications`,
  `negotiations`, `approvals`, `exposure_calcs`, `disruption_events` — note
  `verifications` isn't in the original literal ask but has to be cleared
  too, since it FK's to `disruption_events.id` and Postgres enforces that
  constraint even though sqlite doesn't) and clears the WS ring buffer, then
  calls `app.seed._seed_legacy_disruptions` directly (with a fresh
  `Random(SEED)`) to put the three golden-path disruptions back — same
  function `python -m app.seed --reset` itself uses for that part, so the
  result is the same shape without the ~20k-row vendor/PO/inventory
  regeneration or the schema rebuild. Vendors, POs, inventory, comm events,
  and settlement batches are untouched. `/demo/state` reuses
  `store.metrics_demo.integrations` (the same fixture-backed values
  `GET /metrics/demo` returns — see "Repository layer" above on why that
  endpoint stays fixture-backed) rather than recomputing integration status,
  but calls `app.agents.detectors.ttm_forecast.is_available()` and
  `app.db.session.check_connectivity()` directly for `ttm_loaded` and
  `db_roundtrip_ms` so those two fields are live, not fixture-backed.
- `CONTRACT.md` updated with all of the above, `openapi.json` regenerated via
  `scripts/export_openapi.py`, and `tests/test_contract.py` extended to hit
  every new endpoint (including a duplicate-trigger check on the free-form
  simulate path and a round-trip check that `/demo/reset` actually restores
  `GET /disruptions` to 3 items).

### D1: impact graph

- Confirmed before starting: `POST /api/v1/disruptions/simulate` with
  `{"scenario": "delivery_delay_castings"}` still reaches
  `AWAITING_APPROVAL` after D0 — verified with a clean `POST /demo/reset`
  followed by an uninterrupted run. (The one time it looked broken during
  this phase's own testing, the disruption was stuck at `DIAGNOSED` from an
  *earlier* test process that got force-killed mid-pipeline by an impatient
  `timeout` wrapper — `POST /disruptions/simulate` correctly refuses to
  re-run a disruption that's already past `DETECTED`, so it just kept
  reporting the stuck stage. `POST /demo/reset` is exactly the fix for that
  class of leftover state; don't mistake it for a pipeline regression again.)
- New `app/services/impact.py` — `build_impact_graph(session, disruption) ->
  ImpactGraph`. Pure deterministic graph traversal, same principle as
  `app/services/exposure.py`: **no LLM call anywhere in this module.** Layers
  left to right: `0 VENDOR` → `1 ITEM` (distinct `item_sku` from the vendor's
  open POs) → `2 LINE` (a single aggregate line node, present only if at
  least one item's SKU is tracked in `inventory_snapshots` — reuses
  `app.agents.diagnosis._is_production_critical` per-SKU rather than
  reimplementing that check, per instructions) and a fixed `2 PLANT` anchor
  (the org, always emitted) → `3 ORDER` (open POs carrying a
  `downstream_order_ref`). **The PLANT anchor has no edges** — it's a layout
  landmark for the frontend, not a propagation step; giving it an edge from
  LINE would put two nodes at the same layer on either end of an edge, which
  breaks the "every edge strictly increases layer" invariant the tests
  assert. `summary` reads the disruption's own latest `exposure_calcs` row
  exactly the way `repositories/disruptions.py` does — it is never
  recomputed here, per the "one number" rule in CLAUDE.md's governing
  principle for agents (this module isn't an agent, but the rule still
  applies to anything that puts a ₹ figure in front of a judge).
- Severity tiers (`impact_tier1_exposure_paise` / `impact_tier2_exposure_paise`
  in `app/config.py`, ₹10L / ₹3L) are echoed back in the response as
  `tier_thresholds_paise` so the UI can show its work.
- `GET /api/v1/disruptions/{id}/impact` — router in
  `app/routers/disruptions.py`, same `settings.use_mocks` branch pattern as
  every other disruption endpoint, mock fixture in
  `app/mocks/fixtures/impact.json` (hand-authored, like `forecasts.json` —
  the mock store has no `purchase_orders` table to derive a graph from).
- **Process-lifetime cache**, keyed on `(disruption_id, version)` where
  `version` stands in for an `updated_at` column `DisruptionEvent` doesn't
  have: the max of its own per-stage `*_at` timestamps, plus its latest
  `exposure_calcs.computed_at` if one exists (see
  `app.services.impact.disruption_version_key`) — a new exposure row (e.g.
  Sourcing pricing a backup quote) is what actually changes the graph's
  content between two calls, so it's part of the cache key even though it
  lives on a different table. Plain module-level dict, cleared on restart;
  that's fine, it rebuilds on first read.
- `app/orchestrator/pipeline.py`: `IMPACT_COMPUTED` now fires for real,
  between the `DIAGNOSED` transition and the `SOURCING` transition, with the
  full `ImpactGraph` as payload — this is what makes the frontend's canvas
  animate, so it has to happen during the pipeline run, not only be
  computable on request. Graph building is DB-only and fast but still sync
  SQLAlchemy, so it's wrapped in `asyncio.to_thread` same as every agent call
  in this file (CLAUDE.md's event-loop-stall bug applies here too, even
  though this isn't an agent). One `append_audit` entry per computation
  (action `IMPACT_COMPUTED`, detail carries impacted-node count, at-risk-order
  count, and the `exposure_calc_id` the graph read) — via `append_audit`,
  never a direct `AuditLogEntry` construction.
- `tests/test_impact.py`: in-memory sqlite, no network, no LLM (there's none
  to call) — asserts determinism, every edge references a real node, layers
  strictly increase along every edge, and the summary exposure is checked
  against the actual DB row's value, not a literal. `tests/test_contract.py`
  hits the live endpoint against the shared seeded DB but only asserts
  `VENDOR`/`PLANT` are always present (open-PO count for the seeded D1
  vendor varies run to run since `_generate_purchase_orders` is randomized
  and demo/reset doesn't regenerate purchase orders — don't assert a
  specific non-empty item/order set against that shared disruption again).

### D4: approval broadcast + WhatsApp mock

- **No new table.** `GET /api/v1/phone/messages?disruption_id=` queries existing
  data (disruption alerts, approval cards, negotiation outcomes, settlement
  updates) and deterministically builds the message thread, sorted oldest first.
  This is the honest deliverable: no WhatsApp Business API or Twilio integration,
  just a mock UI fed by DB state. Declared in CONTRACT.md.
- **APPROVAL_DECIDED broadcast enriched**: already existed; updated payload to
  include `disruption_id`, `approval_id`, `decision`, `channel`, `decided_by`
  (previously missing some fields). Broadcast still fires only on fresh
  decisions, never on idempotent replays (CLAUDE.md's rule stands).
- Tests added to `test_contract.py` verifying phone messages endpoint works and
  returns deterministic results.

### D5a: Bolna agent sheet context delivery

- `app/services/agent_sheet.py` is the single context builder for the manually
  operated Bolna voice agent. It reuses `get_vendor_context()` for briefing,
  last terms, and guardrails, and emits fixed positional columns for ranked
  sourcing candidates or the backup pool.
- `GET /api/v1/agent/vendor-sheet.csv` is the dependency-free fallback. Google
  Sheets sync is optional, configured by `GOOGLE_SHEETS_SPREADSHEET_ID`,
  `GOOGLE_SHEETS_WORKSHEET_NAME`, and `GOOGLE_SERVICE_ACCOUNT_JSON`; it clears
  and rewrites the worksheet in one batch and fails soft on missing credentials
  or API errors.
- `agent_sheet_syncs` records the latest status, row count, timestamp, and
  reason using portable columns. Candidate completion triggers sync through
  `asyncio.to_thread` and emits `AGENT_SHEET_SYNCED`; blocking gspread never
  runs on the event loop and never blocks sourcing.
- `resolve_vendor()` establishes D5b's correlation ladder: exact extracted
  `vendor_id`, normalized phone, then newest pending negotiation session.

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
