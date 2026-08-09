# Transaction Agent — Prototype

An AI agent that turns natural-language payment requests into structured,
human-approved, **simulated** transactions. Built as a [LangGraph](https://langchain-ai.github.io/langgraph/)
graph (not a linear script), so human approval gates, parallel execution,
and a full audit trail are first-class parts of the control flow.

No real payment rails are involved anywhere in this phase — every execution
is simulated. Recipient resolution, durable checkpointing, and a real (if
small) approver identity check were added on top of the original
parse → review → approve → execute → log flow to make the graph's state
trustworthy; an HTTP API (`api.py`) put it behind a service and checked it's
in good shape to be imported into watsonx Orchestrate later; a voice
channel (`voice/`, built on [Bolna](https://www.bolna.ai)) puts a phone call
in front of that same API, so a caller can approve a payment by talking to
it; and every store — audit log, recipient directory, users, and the graph's
own checkpoints — now has a real Neon Postgres backend alongside the local
SQLite/JSON one, selected automatically by what's configured in the
environment (see "Neon Postgres" below). `cli.py` and `graph.py`'s public
behavior are unchanged throughout all of this — only which backend a store
talks to changed, never what it does.

## Flow

```
"Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
        │
        ▼
  parse_node                LLM (or regex, --offline) extracts Transaction records
        │
        ▼
  resolve_recipients_node   fuzzy-matches each recipient against a local SQLite
        │                   directory. Exact match -> auto-fills recipient_id.
        │                   Ambiguous / no match -> interrupt() asks a human to
        │                   pick the right one or register a new recipient.
        ▼
  present_review_node       formats a numbered review list + running total
        │
        ▼
  human_approval_node       interrupt() — a human picks which transactions to
        │                   approve (not all-or-nothing) and authenticates
        │                   with username + passphrase against a local user
        │                   table. A bad passphrase re-prompts in place
        │                   (same node, another interrupt()) without
        │                   recording any approval.
        ▼
  route_approved             Send() fans out one branch per transaction (map)
        │
        ▼
  execute_node ×N            Approved -> Processing -> Completed/Failed (simulated);
        │                    Rejected transactions pass through unchanged.
        │                    One branch failing never affects its siblings.
        ▼
  log_node                    reduce step: persists every transition in this
                               run to a JSON audit log, once, after all
                               branches complete.
```

Checkpoints (including any paused interrupt) are written to SQLite or Neon
Postgres as the graph runs, so closing the CLI mid-approval and resuming
later — even in a brand new process — picks up exactly where it left off.
Every audit entry also carries `channel` ("cli" / "api" / "voice"), and,
for voice-originated threads, `call_id` and `transcript_ref` — so the
audit trail can tell a voice-originated approval apart from a CLI or API
one.

## State machine

```
Created -> PendingApproval -> Approved -> Processing -> Completed
                                                       -> Failed
           PendingApproval -> Rejected
```

Illegal transitions raise `IllegalTransitionError` — see
[`transaction_agent/state_machine.py`](transaction_agent/state_machine.py).
Recipient resolution and passphrase retries are logged to the audit trail
too, but they aren't state-machine transitions — they're same-state notes
(`from_status == to_status`) alongside the real transitions.

## Project layout

```
transaction_agent/
  models.py                Transaction, AuditEntry, TransactionStatus (Pydantic)
  state_machine.py          legal transition table, enforced independently of the graph
  parsing_offline.py        regex parser used by --offline (zero credentials)
  llm.py                     ChatWatsonx (IBM Granite) setup + structured extraction
  execution.py               simulate_execution() — the swappable execution seam
  recipient_directory.py     recipient store + fuzzy matching (difflib) — SQLite or Neon
  users.py                   user table, salted+hashed passphrases — SQLite or Neon
  audit.py                    persistent audit log (dedup-by-entry_id, idempotent) — JSON or Neon
  negotiations.py               outbound negotiation call outcomes — SQLite or Neon
  db.py                          shared Postgres (Neon) connection helper for the stores above
  checkpointer.py                 picks SqliteSaver or PostgresSaver the same way
  graph.py                         the compiled LangGraph graph — zero terminal I/O
cli.py                         terminal front end: .invoke(), interrupt handling,
                                --resume, prompts
api.py                         HTTP front end (FastAPI): same .invoke()/Command(resume=...)
                                calls, for a voice agent or any other non-terminal caller
railway.json, start.sh         Railway deployment: one start script picks api.py or
                                voice/adapter.py per service via a SERVICE_ROLE env var
voice/
  state.py                     SQLite state keyed by call_sid: call_sid -> thread_id,
                                 pending selection, per-item disambiguation queue, transcript log
  nlu.py                        dependency-free selection/DTMF parsing + spoken-text formatting
  adapter.py                    the actual webhook endpoints Bolna's tools call — calls api.py
                                 over HTTP, reshapes responses into spoken_text
  sheets.py                      Google Sheets logging for negotiation outcomes (service account)
  setup_sheet.py                  one-time: create + share the negotiation-outcomes sheet
  bolna_agent_config.json       the owner-approval Bolna agent (tools + system prompt)
  bolna_negotiation_agent_config.json  the outbound vendor negotiation Bolna agent
  register_agent.py             registers/updates either agent with Bolna's API (dry-run by default)
smoke_test.py                   standalone watsonx.ai auth check
tests/                          pytest suite
VOICE_TEST_PLAN.md              manual test plan for the voice channel (see "Voice channel" below)
```

`graph.py` never calls `print()` or `input()`. All terminal I/O lives in
`cli.py`; all HTTP lives in `api.py`; the voice channel lives entirely in
`voice/`, which calls `api.py` over HTTP rather than importing the graph
directly. None of the three front ends changes anything in `graph.py` —
they all just call `.invoke()`, `Command(resume=...)`, and
`graph.get_state()` the same way. See "Orchestrate readiness" below for
why a fourth front end (or a native LangGraph import) can be added the
same way, with evidence rather than just an assertion.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your watsonx.ai credentials:

```bash
cp .env.example .env
```

```
WATSONX_API_KEY=...
WATSONX_PROJECT_ID=...
WATSONX_URL=https://<region>.ml.cloud.ibm.com
```

Get an API key at https://cloud.ibm.com/iam/apikeys and a project id from
your watsonx.ai project settings. If any of these three env vars are
missing, the app fails loudly with these instructions — it never silently
falls back to another provider.

Verify auth before running anything else:

```bash
python smoke_test.py
```

Create at least one local approver user (used by the passphrase check, not
watsonx):

```bash
python -m transaction_agent.users create krish
```

## Neon Postgres

Optional — everything above works with zero external dependencies via
local SQLite/JSON files. Set these in `.env` (see `.env.example`) to move
the audit log, recipient directory, users, and graph checkpoints into Neon
instead, all in this database's own `transaction_agent` schema (created
automatically), kept separate from any other service sharing the database
(e.g. this project's own `backend/`, whose tables live in `public`):

```
DATABASE_URL=postgresql://user:pass@host-pooler.region.aws.neon.tech/dbname?sslmode=require&channel_binding=require
DATABASE_URL_DIRECT=postgresql://user:pass@host.region.aws.neon.tech/dbname?sslmode=require&channel_binding=require
```

`DATABASE_URL` (Neon's pooled endpoint) is used for the audit log,
recipient directory, and users table — many short-lived connections, which
pooling is designed for. `DATABASE_URL_DIRECT` (no PgBouncer in front) is
used for the LangGraph checkpointer specifically, which is held open for
as long as a graph object is in use rather than reopened per call.

**Why two endpoints, and why every one of our own tables is
schema-qualified in its SQL (`transaction_agent.audit_entries`, not just
`audit_entries`) instead of relying on a `SET search_path` once per
connection:** PgBouncer transaction-pooling mode can transparently hand
consecutive statements on what looks like one client connection to
*different* backend Postgres sessions. Session-level state — including
`SET search_path` — doesn't survive that handoff. This is a real bug that
was hit and fixed during development (`transaction_agent/db.py`,
`audit.py`, `recipient_directory.py`, `users.py`): an intermittent
`UndefinedTable` error on the pooled endpoint that didn't reproduce in
quick manual checks but did under a real CLI run, because it depends on
pool timing/load, not just code correctness. The checkpointer is exempt
from this because it uses the *direct* endpoint — one dedicated session
per graph object — where `search_path` is safe to rely on, which matters
because LangGraph's own internal SQL isn't schema-qualified and can't be
changed from here.

Every store module keeps accepting the exact same `path` parameter it
always did — a local file path selects SQLite/JSON, a `postgres://` /
`postgresql://` connection string selects Postgres — so nothing calling
into them (`graph.py`, `cli.py`, `api.py`, `voice/adapter.py`) needed to
change. `DEFAULT_AUDIT_LOG_PATH` / `DEFAULT_DIRECTORY_PATH` /
`DEFAULT_USERS_PATH` pick `DATABASE_URL` automatically when it's set
(computed once at import — which is why `.env` is loaded from
`transaction_agent/__init__.py` itself, not from each front end, so it's
guaranteed to happen before those defaults are computed regardless of
import order). `cli.py`/`api.py` similarly default their checkpointer to
Postgres via `transaction_agent/checkpointer.py` when `DATABASE_URL_DIRECT`
is set; pass `--checkpoint-dsn` (CLI) or construct `Settings(checkpoint_dsn=None)`
(API) to force SQLite regardless — this is exactly how the test suite
stays fast and fully offline despite Neon being configured in this
project's own `.env`: every test passes an explicit local path/DSN rather
than relying on the default.

`tests/test_neon_integration.py` is a small opt-in suite (skipped unless
`DATABASE_URL`/`DATABASE_URL_DIRECT` are set) that exercises all four
stores — including the checkpointer-across-a-simulated-restart case —
against the real database, since the pooling bug above is exactly the
kind of thing local-only testing can't catch.

```bash
pytest tests/test_neon_integration.py -v
```

## Running

With watsonx.ai (LLM parsing):

```bash
python cli.py "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
```

With zero credentials (regex parser, `--offline`):

```bash
python cli.py --offline "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
```

The CLI prints a thread id up front — note it down (or just use
`--resume` with no id, which remembers the most recent one):

```bash
python cli.py --resume                    # continue the most recent thread
python cli.py --resume <thread_id>        # continue a specific one, even
                                           # from a different terminal/process
```

You'll be walked through, in order:

1. **Recipient disambiguation** (only if a recipient is ambiguous or
   unrecognized against the local directory) — pick a candidate, register a
   new recipient, or leave it unresolved for now.
2. **Review + approval** — a numbered list with a running total, a
   checkbox-style prompt (comma-separated numbers, `all`, or `none`), the
   combined total of your selection, and an approver username + passphrase
   prompt. A wrong passphrase re-prompts without recording anything.
3. **Simulated execution results**, one line per transaction.

Every transition — including recipient resolution and passphrase
attempts — is appended to `audit_log.json` (`--audit-path` to override).
Checkpoints go to `checkpoints.sqlite` (`--checkpoint-db`), the recipient
directory to `recipient_directory.sqlite` (`--recipient-directory`), and
users to `users.sqlite` (`--users-db`).

## HTTP API

A second front end for the same graph, meant for a voice agent (or any
other non-interactive caller) rather than a terminal:

```bash
export TRANSACTION_AGENT_API_KEY=some-secret   # defaults to "dev-local-key" if unset — dev only
uvicorn api:app --reload
```

Every request needs an `X-API-Key` header matching that key.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /requests` | `{raw_request, requester_id, channel?, call_id?, transcript_ref?, auto_resolve_recipients?}` | `{thread_id, status, review_text?, transactions?, pending_recipients?}` |
| `POST /requests/{thread_id}/disambiguate` | `{choices: {transaction_id: {recipient_id} \| {register_new: {name, notes?}}}}` | same shape as above, once every pending recipient has a choice |
| `POST /requests/{thread_id}/approve` | `{selected_ids, approver_id, passphrase}` | `{thread_id, results[]}` on success; `401` with a clear message on a bad passphrase |
| `GET /requests/{thread_id}` | — | current status: `pending_recipient_disambiguation`, `pending_approval`, or `completed`, with the relevant fields for each |
| `GET /audit/{transaction_id}` | — | full transition history for one transaction |

`auto_resolve_recipients` defaults to `true`, preserving the original
behavior: any `recipient_disambiguation` interrupt is resolved automatically
(top-scored candidate for an `ambiguous` match, register-new for `none`)
before `POST /requests` returns, so a caller that doesn't care can ignore
disambiguation entirely (see `_auto_resolve_recipients()` in `api.py`).
Pass `"auto_resolve_recipients": false` to get `status:
"pending_recipient_disambiguation"` back instead and resolve it explicitly
via `POST /requests/{thread_id}/disambiguate` — this is what the voice
channel uses, since a phone call can just ask the caller directly rather
than have a default guessed for them.

`channel`/`call_id`/`transcript_ref` are optional metadata stamped onto
every audit entry for the thread (see "Flow" above); `channel` defaults to
`"api"` if omitted.

Like the CLI, every request opens its own SQLite checkpoint connection via
`build_graph()` and closes it when the request finishes — see "Orchestrate
readiness" below for why that's deliberate, not just convenient. `X-API-Key`
is checked with a plain string compare (not constant-time) — fine for a
single local secret in this phase, worth revisiting before anything
internet-facing.

## Voice channel

A phone call as a third front end, via [Bolna](https://www.bolna.ai). Same
principle as `cli.py`/`api.py`: `voice/adapter.py` doesn't parse requests,
decide approvals, or execute anything — it calls `api.py` over HTTP and
translates between its JSON and what Bolna's tool-calling / TTS needs.

```
caller ──(phone)── Bolna (STT/LLM/TTS) ──(tool-call webhooks)── voice/adapter.py ──(HTTP)── api.py ── graph.py
```

**Run it** (with `api.py` already running):

```bash
export TRANSACTION_AGENT_API_BASE_URL=http://127.0.0.1:8000
export TRANSACTION_AGENT_API_KEY=some-secret        # must match api.py's key
export VOICE_ADAPTER_SHARED_SECRET=some-other-secret # what Bolna's tools authenticate with
uvicorn voice.adapter:app --reload --port 8100
```

**Register the agent(s)** with Bolna once the adapter is reachable at a
public URL (e.g. via `ngrok http 8100` in dev, or a real deploy — see
"Deployment" below):

```bash
export BOLNA_API_KEY=...            # from the Bolna Dashboard > Developers
export VOICE_ADAPTER_BASE_URL=https://your-tunnel-or-host.example.com
python -m voice.register_agent                          # dry run: owner-approval agent
python -m voice.register_agent --submit                 # actually creates it via Bolna's API
python -m voice.register_agent --config negotiation --submit  # the outbound negotiation agent (see below)
```

Point a Bolna phone number's inbound routing at the approval agent
(`POST https://api.bolna.ai/inbound/setup` with that agent's `agent_id`
and the number's `phone_number_id` — find the latter via
`GET /phone-numbers/all`), and use the negotiation agent's `agent_id` as
the `agent_id` in `POST /call` when placing outbound vendor calls.

**Call flow**, driven by the system prompt in `voice/bolna_agent_config.json`:

1. Caller states a payment request. Bolna's tool-calling passes the raw
   transcript straight to `POST /voice/requests` — the prompt explicitly
   tells the LLM not to reformat or restructure it; `parse_node` (via
   `api.py`) does the actual parsing, same as any other channel.
2. If a recipient is ambiguous or unknown, the caller resolves it one item
   at a time via `POST /voice/requests/disambiguate` — the same
   `interrupt()`/`Command(resume=...)` mechanics as the CLI's disambiguation
   step, just reached through `api.py`'s `POST /requests/{id}/disambiguate`
   instead of a terminal prompt.
3. The review is read back item-by-item plus a total
   (`voice/nlu.format_review_for_voice`) — spoken amounts, not "12,000.00
   INR". The prompt instructs the LLM to read the tool's `spoken_text`
   verbatim rather than re-deriving numbers itself.
4. Selection (`POST /voice/requests/select`) only ever *records* a pending
   selection and reads back its total — it never approves anything.
   `POST /voice/requests/confirm` is the only endpoint that can call
   `api.py`'s `/approve`, and only after seeing an explicit affirmative
   word — the selection utterance itself is never treated as a
   confirmation, by design (see the module docstring in `voice/adapter.py`).
5. The PIN *is* the Phase 2 passphrase check, unweakened — `confirm_payment`
   passes `approver_username`/`pin` straight through as
   `approver_id`/`passphrase` to `api.py`'s `/approve`. A wrong PIN doesn't
   clear the pending selection, so a retry doesn't need to re-state which
   payments to approve.
6. The final readback names each transaction's simulated result and
   explicitly states that no real funds moved.

**Design decisions worth knowing about:**

- **State is keyed by `call_sid`, never `thread_id`.** Bolna fills a tool
  call's parameters from what its LLM remembers of the conversation;
  asking it to correctly recall and re-embed an opaque 36-character UUID
  turn after turn is a real, avoidable failure mode. `call_sid` is
  auto-injected by Bolna into every tool call via templating
  (`%(call_sid)s`), so it's never something the LLM has to "remember."
  `voice/state.py` holds the `call_sid -> thread_id` mapping (and pending
  selection, and disambiguation progress) server-side.
- **Every endpoint returns HTTP 200 with a `spoken_text` explaining what
  happened, even on failure.** A phone call has no good way to surface a
  raw HTTP error, so failures (no request started yet, nothing to confirm,
  a rejected PIN) become something sayable instead of an opaque 4xx/5xx.
- **DTMF is a documented convention, not a confirmed Bolna schema.**
  Bolna's docs confirm DTMF capture exists but don't publish its exact
  webhook shape, so `voice/nlu.parse_dtmf_selection` defines one (`*`
  separated digits, `#` to terminate, `0`/`9` shortcuts for none/all) —
  see `VOICE_TEST_PLAN.md`'s "Known gaps" for what a real call needs to
  confirm.
- **`audit_log.json` entries for a voice thread carry `channel: "voice"`,
  `call_id`, and `transcript_ref`** (a pointer into
  `voice/state.py`'s per-call transcript log) — see `graph.py`'s
  `_extract_meta()`.

See [`VOICE_TEST_PLAN.md`](VOICE_TEST_PLAN.md) for the five required test
scenarios (clean approval, partial selection, voice disambiguation, wrong
PIN, hangup-mid-flow) — what's automated in `tests/test_voice_adapter.py`
versus what only a real call can verify, and exactly how to check each one.

### Outbound vendor negotiation (a second, separate agent)

The owner-approval agent above is for someone calling *in* to approve a
payment. Placing *outbound* calls to negotiate a price with a vendor is a
different conversation with a different job — extract who you're talking
to and what they'll agree to, stay warm and unhurried, and transfer to a
human the moment they ask — so it's a second Bolna agent
(`voice/bolna_negotiation_agent_config.json`), not a mode of the first one.

It has exactly one tool, `record_negotiation_outcome`, called once at the
end of the call → `POST /voice/negotiation/outcome`:

- **Declined**: recorded in `transaction_agent/negotiations.py` (same
  dual SQLite/Postgres backend as everything else) and, if configured, a
  row in the Google Sheet (see below). Nothing further happens.
- **Accepted**: recorded the same way, *and* a normal payment request is
  created via the same `POST /requests` any other channel uses (recipient
  auto-resolved, since this agent has no disambiguation sub-flow of its
  own) — so the result lands in the owner's regular approval queue, not a
  side channel. The negotiation record's `transaction_id` links back to it.

The call-transfer-to-a-human behavior ("if the vendor would like to speak
to the person directly") relies on whatever transfer/handoff capability is
already configured on the Bolna number/account — this repo doesn't define
or override that, only instructs the negotiation prompt to use it
immediately and without argument whenever asked.

**Google Sheets logging** (`voice/sheets.py`) is a supplementary view for
the owner, not the source of truth — a service account (machine
credential, no interactive OAuth), gated so a Sheets failure never blocks
recording an outcome:

```bash
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service-account-key.json)"
python -m voice.setup_sheet --share-with owner@example.com
# prints a spreadsheet ID — set NEGOTIATION_SPREADSHEET_ID to it
```

### Deployment

`api.py` and `voice/adapter.py` are deployed as two Railway services from
this same repo — `start.sh` picks which one to run via a `SERVICE_ROLE`
env var (`api` or `voice`) per service, so nothing is duplicated. See
`railway.json` / `start.sh`. Both services need Railway's dynamically
assigned `$PORT` — the generated domain's target port must match it (check
via `railway logs` if you get a 502; Railway may not pick 8000/8100).

## Orchestrate readiness

watsonx Orchestrate can import a LangGraph agent directly (via the
Orchestrate ADK CLI) rather than going through a hand-written API layer.
Before assuming that'll work, three things need to hold:

1. **No hidden stdin/stdout dependency.** `graph.py` and everything it
   imports (`models.py`, `state_machine.py`, `execution.py`,
   `parsing_offline.py`, `audit.py`, `recipient_directory.py`, `llm.py`)
   call neither `print()` nor `input()` — checked by AST, not just grep,
   in `tests/test_readiness.py::test_core_modules_have_no_stdin_stdout_dependency`.
   `users.py` has one `print()`, confined to its `python -m
   transaction_agent.users` CLI helper, which an import never touches
   (`test_users_module_confines_stdio_to_its_cli_helper`).
2. **No global mutable business state.** Audited module-by-module: every
   module-level value is either a constant, an `os.environ` default read
   once at import, a compiled regex, or the frozen state-transition table.
   The one mutable module-level object is `audit._lock`, a
   `threading.Lock` — that's a concurrency primitive protecting concurrent
   writes to the JSON audit file, not business/conversation state, and it
   doesn't create any cross-thread (in the LangGraph sense) leakage.
3. **`build_graph()` is safe to call fresh per call site.** Every node
   function is a closure defined inside `build_graph()`, capturing only
   the arguments passed to that specific call — two calls never share
   anything. `tests/test_readiness.py` proves this behaviorally, not just
   by inspection: independently-built graphs run interleaved with
   different SQLite stores and never see each other's data
   (`test_independently_built_graphs_share_no_state`), and multiple fresh
   `build_graph()` calls against the *same* checkpoint file — mirroring
   exactly what `api.py`'s per-request `get_graph()` dependency does —
   correctly hand a thread started by one instance off to a completely
   different instance for its resume (`test_build_graph_called_fresh_per_call_against_same_store_is_safe`).

**Net result: nothing in `graph.py` needed to change for this.** The
design from earlier phases (closures over locally-scoped arguments, no
terminal I/O, file-backed rather than in-process state) already satisfied
all three properties; this pass exists to have evidence for that claim
instead of just asserting it.

## Tests

```bash
pytest
```

Covers: every legal/illegal state transition, that transactions left
unselected are marked `Rejected` rather than silently dropped, that
resuming an `interrupt()` doesn't duplicate audit entries, that one failing
execution in the fan-out doesn't affect its siblings, ambiguous-recipient
disambiguation (and new-recipient registration) via the same interrupt
machinery, that a bad passphrase re-prompts without recording an approval,
recipient/user store unit tests, that a paused thread resumes correctly
across a simulated process restart (fresh SQLite connection, fresh graph
object, same checkpoint file), the full HTTP API happy path plus
wrong-passphrase and unknown/completed-thread error cases via `TestClient`,
API-key enforcement, the Orchestrate-readiness checks above, the voice
adapter's NLU parsing and every mechanical piece of the call flow (select →
confirm gate, PIN retry, one-at-a-time disambiguation, channel/call_id/
transcript_ref audit tagging, and a "hangup" leaving the thread parked
rather than approved or lost), the negotiation-outcomes store, and the
negotiation-outcome endpoint (accepted creates a linked pending payment
request with the vendor auto-registered as a new recipient; declined
doesn't; both record regardless) — everything short of an actual phone call,
which is what `VOICE_TEST_PLAN.md` is for. All of the above run fully
offline against local SQLite/JSON, regardless of whether Neon is
configured in `.env` — `tests/test_neon_integration.py` is the separate,
opt-in suite that hits the real database (see "Neon Postgres" above).

## Where the next phases plug in

- **Real payment provider**: swap `execute_fn` in `build_graph()`
  ([`transaction_agent/graph.py`](transaction_agent/graph.py)) —
  `execute_node` calls whatever function it's given; nothing else in the
  graph needs to change. The default is
  [`simulate_execution`](transaction_agent/execution.py).
- **Real recipient directory**: `recipient_directory.py` is a local SQLite
  table with `difflib`-based fuzzy matching — swap `resolve_recipient_fn`
  / `register_recipient_fn` in `build_graph()` for calls into a real
  vendor-master system; `resolve_recipients_node` doesn't otherwise change.
- **Real approver auth**: `users.py` is a local salted-hash user table —
  swap `verify_user_fn` in `build_graph()` for a call to real SSO/enterprise
  auth; `human_approval_node`'s retry-loop shape stays the same.
- **Checkpointer / persistence**: done — `SqliteSaver`/`PostgresSaver` and
  the audit/recipient/user stores both pick Neon automatically when
  configured (see "Neon Postgres" above). What's still local-only no
  matter what: `voice/state.py` (call-scoped, short-lived by nature) and
  the `.transaction_agent_last_thread` convenience file.
- **Different front end**: `api.py` is one example — reuse
  `transaction_agent.graph.build_graph()` directly from anything else the
  same way: `.invoke()`/`.stream()`, catch `__interrupt__`, resume with
  `Command(resume=...)`. `graph.get_state(config)` is how both
  `cli.py --resume` and `GET /requests/{thread_id}` peek a pending
  interrupt without resuming it.
- **A real DTMF payload from Bolna**: `voice/nlu.parse_dtmf_selection`
  defines its own convention because Bolna's published docs don't specify
  one — the first real call using a keypad should confirm what Bolna
  actually sends and adjust `voice/adapter.py`'s DTMF parameter handling
  if it differs. See `VOICE_TEST_PLAN.md`'s "Known gaps."
- **Native watsonx Orchestrate import**: see "Orchestrate readiness" above
  — the graph itself is already in a state where this should be a
  configuration exercise (via the Orchestrate ADK CLI) rather than a code
  change, though it hasn't been attempted against a real Orchestrate
  environment.
- **Audit log backend**: `transaction_agent/audit.py` is a small JSON-file
  store behind two functions (`append_entries`, `read_all`). Swapping to
  SQLite means changing that module only.
