# Transaction Agent — Prototype

An AI agent that turns natural-language payment requests into structured,
human-approved, **simulated** transactions. Built as a [LangGraph](https://langchain-ai.github.io/langgraph/)
graph (not a linear script), so human approval gates, parallel execution,
and a full audit trail are first-class parts of the control flow.

No real payment rails are involved anywhere in this phase — every execution
is simulated. This phase adds recipient resolution, durable checkpointing,
and a real (if small) approver identity check on top of the original
parse → review → approve → execute → log flow, so the graph's state is
trustworthy enough to eventually sit behind a service.

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
smoke_test.py                   standalone watsonx.ai auth check
tests/                          pytest suite
```

`graph.py` never calls `print()` or `input()`. All terminal I/O lives in
`cli.py`. This split is what lets the same graph run behind a different
front end later — a service API, a voice agent, a watsonx Orchestrate
import — without touching graph.py at all.

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
recipient/user store unit tests, and that a paused thread resumes correctly
across a simulated process restart (fresh SQLite connection, fresh graph
object, same checkpoint file).

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
- **Different front end**: reuse `transaction_agent.graph.build_graph()`
  directly. Drive it with `.invoke()`/`.stream()`, catch `__interrupt__`,
  and resume with `Command(resume=...)` from a web service, a voice agent,
  or a watsonx Orchestrate skill instead of `cli.py`. `graph.get_state(config)`
  is how `cli.py --resume` peeks a pending interrupt without resuming it —
  useful for a service that needs to render "what's this thread waiting on"
  before the human responds.
- **Audit log backend**: `transaction_agent/audit.py` is a small JSON-file
  store behind two functions (`append_entries`, `read_all`). Swapping to
  SQLite means changing that module only.
