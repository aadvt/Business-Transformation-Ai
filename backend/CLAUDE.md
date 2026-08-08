# Sanjeevani backend — locked decisions

This file records decisions made across phases so future sessions don't
re-litigate them. Read this before changing conventions.

## Phase

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
