# Transaction Agent — Prototype

An AI agent that turns natural-language payment requests into structured,
human-approved, **simulated** transactions. Built as a [LangGraph](https://langchain-ai.github.io/langgraph/)
graph (not a linear script), so human approval gates, parallel execution,
and a full audit trail are first-class parts of the control flow.

No real payment rails are involved anywhere in this phase — every execution
is simulated. Recipient resolution, durable checkpointing, and a real (if
small) approver identity check were added on top of the original
parse → review → approve → execute → log flow to make the graph's state
trustworthy; this phase puts it behind an HTTP API (`api.py`, alongside the
unchanged `cli.py`) and checks it's in good shape to be imported into
watsonx Orchestrate later.

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

Checkpoints (including any paused interrupt) are written to SQLite as the
graph runs, so closing the CLI mid-approval and resuming later — even in a
brand new process — picks up exactly where it left off.

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
  recipient_directory.py     SQLite recipient store + fuzzy matching (difflib)
  users.py                   SQLite user table, salted+hashed passphrases
  audit.py                    persistent JSON audit log (dedup-by-entry_id, idempotent)
  graph.py                     the compiled LangGraph graph — zero terminal I/O
cli.py                         terminal front end: .invoke(), interrupt handling,
                                --resume, prompts
api.py                         HTTP front end (FastAPI): same .invoke()/Command(resume=...)
                                calls, for a future voice agent or other non-terminal caller
smoke_test.py                   standalone watsonx.ai auth check
tests/                          pytest suite
```

`graph.py` never calls `print()` or `input()`. All terminal I/O lives in
`cli.py`; all HTTP lives in `api.py`. Neither front end changes anything
in `graph.py` — both just call `.invoke()`, `Command(resume=...)`, and
`graph.get_state()` the same way. See "Orchestrate readiness" below for
why a third front end (or a native LangGraph import) can be added the same
way, with evidence rather than just an assertion.

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

A second front end for the same graph, meant for a future voice agent (or
any other non-interactive caller) rather than a terminal:

```bash
export TRANSACTION_AGENT_API_KEY=some-secret   # defaults to "dev-local-key" if unset — dev only
uvicorn api:app --reload
```

Every request needs an `X-API-Key` header matching that key.

| Endpoint | Body | Returns |
|---|---|---|
| `POST /requests` | `{raw_request, requester_id}` | `{thread_id, review_text, transactions[]}` — parsed and ready for approval |
| `POST /requests/{thread_id}/approve` | `{selected_ids, approver_id, passphrase}` | `{thread_id, results[]}` on success; `401` with a clear message on a bad passphrase |
| `GET /requests/{thread_id}` | — | current status: `pending_recipient_disambiguation`, `pending_approval`, or `completed`, with the relevant fields for each |
| `GET /audit/{transaction_id}` | — | full transition history for one transaction |

One gap between the graph and this endpoint list: there's no endpoint for
a caller to answer a `recipient_disambiguation` interrupt mid-request (the
spec for this API didn't include one). Rather than leave `POST /requests`
unable to complete, it auto-resolves any such interrupt itself — top-scored
candidate for an `ambiguous` match, register-new for `none` — before
returning the review to the caller (see `_auto_resolve_recipients()` in
`api.py`). `recipient_id` on the returned transactions tells you which way
it went. A future phase could add a dedicated endpoint (and skip the
auto-resolve) if a caller needs to ask the user directly instead.

Like the CLI, every request opens its own SQLite checkpoint connection via
`build_graph()` and closes it when the request finishes — see "Orchestrate
readiness" below for why that's deliberate, not just convenient. `X-API-Key`
is checked with a plain string compare (not constant-time) — fine for a
single local secret in this phase, worth revisiting before anything
internet-facing.

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
API-key enforcement, and the Orchestrate-readiness checks above.

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
- **Checkpointer**: this phase uses `SqliteSaver` (see `cli.py`). For a
  multi-instance service deployment, swap in `PostgresSaver` — same
  `checkpointer=` argument to `build_graph()`.
- **Different front end**: `api.py` is one example — reuse
  `transaction_agent.graph.build_graph()` directly from anything else the
  same way: `.invoke()`/`.stream()`, catch `__interrupt__`, resume with
  `Command(resume=...)`. `graph.get_state(config)` is how both
  `cli.py --resume` and `GET /requests/{thread_id}` peek a pending
  interrupt without resuming it.
- **A dedicated recipient-disambiguation endpoint**: `api.py` currently
  auto-resolves that interrupt inside `POST /requests` (see "HTTP API"
  above) because the endpoint list this phase specified didn't include a
  way for a caller to answer it. A voice agent that wants to ask the user
  directly would need a `POST /requests/{thread_id}/resolve-recipient`-style
  endpoint instead — same interrupt/resume mechanics, just exposed rather
  than auto-decided.
- **Native watsonx Orchestrate import**: see "Orchestrate readiness" above
  — the graph itself is already in a state where this should be a
  configuration exercise (via the Orchestrate ADK CLI) rather than a code
  change, though it hasn't been attempted against a real Orchestrate
  environment.
- **Audit log backend**: `transaction_agent/audit.py` is a small JSON-file
  store behind two functions (`append_entries`, `read_all`). Swapping to
  SQLite means changing that module only.
