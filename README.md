# Transaction Agent — Phase 1 Prototype

An AI agent that turns natural-language payment requests into structured,
human-approved, **simulated** transactions. Built as a [LangGraph](https://langchain-ai.github.io/langgraph/)
graph (not a linear script), so a human approval gate, parallel execution,
and a full audit trail are first-class parts of the control flow.

No real payment rails are involved anywhere in this phase — every execution
is simulated.

## Flow

```
"Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
        │
        ▼
  parse_node            LLM (or regex, --offline) extracts Transaction records
        │
        ▼
  present_review_node   formats a numbered review list + running total
        │
        ▼
  human_approval_node   interrupt() — pauses for a human to pick which
        │               transactions to approve (not all-or-nothing)
        ▼
  route_approved         Send() fans out one branch per transaction (map)
        │
        ▼
  execute_node ×N        Approved -> Processing -> Completed/Failed (simulated);
        │                 Rejected transactions pass through unchanged.
        │                 One branch failing never affects its siblings.
        ▼
  log_node                reduce step: persists every transition in this
                           run to a JSON audit log, once, after all
                           branches complete.
```

## State machine

```
Created -> PendingApproval -> Approved -> Processing -> Completed
                                                       -> Failed
           PendingApproval -> Rejected
```

Illegal transitions raise `IllegalTransitionError` — see
[`transaction_agent/state_machine.py`](transaction_agent/state_machine.py).

## Project layout

```
transaction_agent/
  models.py           Transaction, AuditEntry, TransactionStatus (Pydantic)
  state_machine.py     legal transition table, enforced independently of the graph
  parsing_offline.py   regex parser used by --offline (zero credentials)
  llm.py                ChatWatsonx (IBM Granite) setup + structured extraction
  execution.py          simulate_execution() — the swappable execution seam
  audit.py               persistent JSON audit log (dedup-by-entry_id, idempotent)
  graph.py                the compiled LangGraph graph — zero terminal I/O
cli.py                    terminal front end: .invoke(), interrupt handling, prompts
smoke_test.py              standalone watsonx.ai auth check
tests/                     pytest suite
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

## Running

With watsonx.ai (LLM parsing):

```bash
python cli.py "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
```

With zero credentials (regex parser, `--offline`):

```bash
python cli.py --offline "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
```

Either way you'll see a numbered review list, a checkbox-style prompt to
pick which transactions to approve (comma-separated numbers, `all`, or
`none`), the combined total of your selection, a confirmation prompt, and
then simulated execution results per transaction. Every transition is
appended to `audit_log.json` (override with `--audit-path`).

## Tests

```bash
pytest
```

Covers: every legal/illegal state transition, that transactions left
unselected are marked `Rejected` in the output rather than silently
dropped, that resuming an `interrupt()` doesn't duplicate audit entries,
and that one failing execution in the fan-out doesn't affect its siblings.

## Where the next phases plug in

- **Real payment provider**: swap `execute_fn` in `build_graph()`
  ([`transaction_agent/graph.py`](transaction_agent/graph.py)) —
  `execute_node` calls whatever function it's given; nothing else in the
  graph needs to change. The default is
  [`simulate_execution`](transaction_agent/execution.py).
- **Real recipient directory**: `Transaction.recipient_id` is already in
  the data model and always `null` today. A lookup step (fuzzy-match
  `recipient` text against a directory, or a dedicated `resolve_recipient_node`)
  would populate it before `present_review_node`.
- **Persistent checkpointer**: this phase uses `InMemorySaver`, so an
  in-flight approval is lost if the process restarts. Swapping in a
  persistent checkpointer (e.g. `SqliteSaver`/`PostgresSaver`) is a
  one-line change in `build_graph()` and is the natural upgrade before any
  real deployment — approvals should survive a restart.
- **Different front end**: reuse `transaction_agent.graph.build_graph()`
  directly. Drive it with `.invoke()`/`.stream()`, catch `__interrupt__`,
  and resume with `Command(resume=...)` from a web service, a voice agent,
  or a watsonx Orchestrate skill instead of `cli.py`.
- **Audit log backend**: `transaction_agent/audit.py` is a small JSON-file
  store behind two functions (`append_entries`, `read_all`). Swapping to
  SQLite means changing that module only.
