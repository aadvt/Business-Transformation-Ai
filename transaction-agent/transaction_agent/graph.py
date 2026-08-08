"""The Transaction Agent as a LangGraph graph. Zero terminal I/O in this
module — no print(), no input(). All CLI driving lives in cli.py, so this
graph can be reused behind a different front end (a service API, a voice
agent, a watsonx Orchestrate import) later.

    parse_node -> resolve_recipients_node (interrupt, only if any recipient
                    is ambiguous or unknown against the local directory)
        -> present_review_node -> human_approval_node (interrupt, retries
             in-place on a bad passphrase)
        -> route_approved (Send fan-out, one execute_node branch per transaction: map)
            -> execute_node (Approved -> Processing -> Completed/Failed; Rejected passes through)
        -> log_node (single fan-in step over the Annotated[list, operator.add]
                      audit_log reducer once every branch has completed: reduce)

Both `resolve_recipients_node` and `human_approval_node` call interrupt()
as the first thing that can possibly pause them, with NO side effects
(writes, audit entries) before that point: on resume LangGraph re-runs the
node from the top, replaying every earlier interrupt() call in the same
node with its previously-supplied resume value before reaching (or pausing
at) the next new one. `human_approval_node` uses exactly this to implement
a passphrase-retry loop: each failed attempt is a distinct interrupt()
call; only the code after the loop — which runs exactly once, on the
attempt that verifies — writes anything.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt  # noqa: F401 (Command re-exported for cli.py convenience)

from . import audit as audit_store
from . import recipient_directory
from . import users as users_store
from .execution import simulate_execution
from .llm import parse_with_llm
from .models import AuditEntry, Transaction, TransactionStatus, utcnow_iso
from .parsing_offline import parse_offline
from .state_machine import require_legal_transition

Status = TransactionStatus


class TransactionAgentState(TypedDict, total=False):
    raw_input: str
    offline: bool
    transactions: list[dict[str, Any]]
    review_text: str
    approved_by: str
    audit_log: Annotated[list[dict[str, Any]], operator.add]
    processed_transactions: Annotated[list[dict[str, Any]], operator.add]

    # Which front end originated this thread, set once by whoever calls the
    # first .invoke() and left untouched afterward (no node overwrites these,
    # so the value persists across every resume for the life of the thread).
    # Every audit entry for the thread is tagged with these via _extract_meta().
    channel: Optional[str]  # "cli" | "api" | "voice"
    call_id: Optional[str]
    transcript_ref: Optional[str]

    # branch-local input, only meaningful inside an execute_node Send() call.
    # Every parallel execute_node branch reads its own "transaction" as an
    # isolated input; none of them may return "transaction" as an output key,
    # since concurrent writes to a plain (non-Annotated) key in the same
    # superstep raise InvalidUpdateError. Only Annotated keys go back out.
    transaction: dict[str, Any]


def _extract_meta(state: TransactionAgentState) -> dict[str, Optional[str]]:
    return {
        "channel": state.get("channel"),
        "call_id": state.get("call_id"),
        "transcript_ref": state.get("transcript_ref"),
    }


def _audit_entry(
    transaction_id: str,
    from_status: Optional[Status],
    to_status: Status,
    note: str,
    timestamp: str,
    meta: Optional[dict[str, Optional[str]]] = None,
) -> dict:
    return AuditEntry(
        transaction_id=transaction_id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value,
        timestamp=timestamp,
        note=note,
        **(meta or {}),
    ).model_dump(mode="json")


def _same_state_entry(
    transaction_id: str,
    status_value: str,
    note: str,
    timestamp: str,
    meta: Optional[dict[str, Optional[str]]] = None,
) -> dict:
    """A logged event that isn't a state-machine transition (e.g. recipient
    resolution) — from_status/to_status are the unchanged current status."""
    return AuditEntry(
        transaction_id=transaction_id,
        from_status=status_value,
        to_status=status_value,
        timestamp=timestamp,
        note=note,
        **(meta or {}),
    ).model_dump(mode="json")


def _format_review(transactions: list[dict[str, Any]]) -> str:
    if not transactions:
        return "No transactions were parsed from that input."
    lines = []
    total = 0.0
    for idx, tx in enumerate(transactions, start=1):
        purpose = f" ({tx['purpose']})" if tx.get("purpose") else ""
        lines.append(f"[{idx}] {tx['recipient']}: {tx['amount']:,.2f} {tx['currency']}{purpose}")
        total += tx["amount"]
    lines.append(f"\nTotal ({len(transactions)} transactions): {total:,.2f}")
    return "\n".join(lines)


def build_graph(
    *,
    execute_fn=None,
    llm_parse_fn=None,
    checkpointer=None,
    audit_path: Optional[str] = None,
    recipient_directory_path: Optional[str] = None,
    users_path: Optional[str] = None,
    resolve_recipient_fn=None,
    register_recipient_fn=None,
    verify_user_fn=None,
):
    """Compile the Transaction Agent graph.

    execute_fn: swappable (transaction_dict) -> {"success": bool, ...}. Defaults
        to the simulated executor; pass a real payment-provider call here later.
    llm_parse_fn: swappable (text) -> ParsedTransactionList. Defaults to the
        watsonx.ai structured-output parser; used unless state["offline"] is True,
        in which case the regex parser always runs regardless of this argument.
    checkpointer: defaults to InMemorySaver(). Pass a SqliteSaver (see cli.py) to
        survive process restarts across an interrupt().
    audit_path: file the persistent audit log is written to. Defaults to
        audit_store.DEFAULT_AUDIT_LOG_PATH (override for tests / multiple runs).
    recipient_directory_path / users_path: SQLite files for the recipient
        directory and the local approver user table, respectively.
    resolve_recipient_fn / register_recipient_fn / verify_user_fn: swappable
        seams over recipient_directory.resolve/register and users.verify,
        mainly so tests can inject fakes without touching disk paths.
    """
    execute_fn = execute_fn or simulate_execution
    llm_parse_fn = llm_parse_fn or parse_with_llm
    audit_path = audit_path or audit_store.DEFAULT_AUDIT_LOG_PATH
    recipient_directory_path = recipient_directory_path or recipient_directory.DEFAULT_DIRECTORY_PATH
    users_path = users_path or users_store.DEFAULT_USERS_PATH
    resolve_recipient_fn = resolve_recipient_fn or recipient_directory.resolve
    register_recipient_fn = register_recipient_fn or recipient_directory.register
    verify_user_fn = verify_user_fn or users_store.verify

    def parse_node(state: TransactionAgentState) -> dict:
        text = state["raw_input"]
        parsed = parse_offline(text) if state.get("offline") else llm_parse_fn(text)
        meta = _extract_meta(state)

        now = utcnow_iso()
        transactions = []
        audit_entries = []
        for item in parsed.transactions:
            tx = Transaction(
                recipient=item.recipient,
                amount=item.amount,
                currency=item.currency,
                purpose=item.purpose,
                status=Status.CREATED,
                interpreted_from=text,
                created_at=now,
            )
            transactions.append(tx.model_dump(mode="json"))
            audit_entries.append(_audit_entry(tx.id, None, Status.CREATED, "Parsed from user input", now, meta))

        return {"transactions": transactions, "audit_log": audit_entries}

    def resolve_recipients_node(state: TransactionAgentState) -> dict:
        transactions = state["transactions"]
        meta = _extract_meta(state)

        # resolve_recipient_fn is a read-only directory lookup: idempotent,
        # so it's safe to call before interrupt() and it will simply be
        # recomputed (not duplicated) every time this node re-runs on resume.
        resolutions = {tx["id"]: resolve_recipient_fn(tx["recipient"], path=recipient_directory_path) for tx in transactions}
        pending = [tx for tx in transactions if resolutions[tx["id"]].status != "auto"]

        choices: dict[str, Any] = {}
        if pending:
            decision = interrupt(
                {
                    "kind": "recipient_disambiguation",
                    "pending": [
                        {
                            "transaction_id": tx["id"],
                            "recipient_text": tx["recipient"],
                            "amount": tx["amount"],
                            "status": resolutions[tx["id"]].status,
                            "candidates": [
                                {"recipient_id": c.recipient_id, "name": c.name, "score": c.score}
                                for c in resolutions[tx["id"]].candidates
                            ],
                        }
                        for tx in pending
                    ],
                }
            )
            choices = decision.get("choices") or {}

        now = utcnow_iso()
        updated = []
        audit_entries = []
        for tx in transactions:
            res = resolutions[tx["id"]]
            if res.status == "auto":
                recipient_id = res.recipient_id
                note = f"Recipient auto-resolved to {recipient_id}"
            else:
                choice = choices.get(tx["id"]) or {}
                register_new = choice.get("register_new")
                if register_new:
                    recipient_id = register_recipient_fn(
                        register_new.get("name") or tx["recipient"],
                        notes=register_new.get("notes"),
                        path=recipient_directory_path,
                    )
                    note = f"New recipient registered: {recipient_id}"
                elif choice.get("recipient_id"):
                    recipient_id = choice["recipient_id"]
                    note = f"Recipient selected by human: {recipient_id}"
                else:
                    recipient_id = None
                    note = "Recipient left unresolved"
            tx = {**tx, "recipient_id": recipient_id}
            updated.append(tx)
            audit_entries.append(_same_state_entry(tx["id"], tx["status"], note, now, meta))

        return {"transactions": updated, "audit_log": audit_entries}

    def present_review_node(state: TransactionAgentState) -> dict:
        now = utcnow_iso()
        meta = _extract_meta(state)
        updated = []
        audit_entries = []
        for tx in state["transactions"]:
            require_legal_transition(Status(tx["status"]), Status.PENDING_APPROVAL)
            tx = {**tx, "status": Status.PENDING_APPROVAL.value, "entered_queue_at": now}
            updated.append(tx)
            audit_entries.append(
                _audit_entry(tx["id"], Status.CREATED, Status.PENDING_APPROVAL, "Entered approval queue", now, meta)
            )
        return {
            "transactions": updated,
            "review_text": _format_review(updated),
            "audit_log": audit_entries,
        }

    def human_approval_node(state: TransactionAgentState) -> dict:
        # Nothing before/inside this loop writes anything: each failed
        # passphrase attempt is its own interrupt() call, replayed verbatim
        # on every re-run of this node, until one verifies and the loop
        # breaks. Only the code after the loop (which then runs exactly
        # once) applies transitions and writes audit entries.
        error = None
        selected_ids_raw: list[str] = []
        username = None
        while True:
            decision = interrupt(
                {
                    "kind": "transaction_approval",
                    "review_text": state["review_text"],
                    "transactions": state["transactions"],
                    "error": error,
                }
            )
            username = decision.get("username")
            passphrase = decision.get("passphrase")
            selected_ids_raw = decision.get("selected_ids") or []
            if verify_user_fn(username, passphrase, path=users_path):
                break
            error = f"Authentication failed for '{username}'. Please try again."

        selected_ids = set(selected_ids_raw)
        approved_by = username
        now = utcnow_iso()
        meta = _extract_meta(state)

        updated = []
        audit_entries = []
        for tx in state["transactions"]:
            if tx["id"] in selected_ids:
                require_legal_transition(Status(tx["status"]), Status.APPROVED)
                tx = {**tx, "status": Status.APPROVED.value, "approved_by": approved_by, "approved_at": now}
                audit_entries.append(
                    _audit_entry(
                        tx["id"], Status.PENDING_APPROVAL, Status.APPROVED, f"approved_by={approved_by}", now, meta
                    )
                )
            else:
                require_legal_transition(Status(tx["status"]), Status.REJECTED)
                tx = {**tx, "status": Status.REJECTED.value}
                audit_entries.append(
                    _audit_entry(
                        tx["id"], Status.PENDING_APPROVAL, Status.REJECTED, "Not selected for approval", now, meta
                    )
                )
            updated.append(tx)

        return {"transactions": updated, "audit_log": audit_entries, "approved_by": approved_by}

    def route_approved(state: TransactionAgentState):
        # map: one execute_node branch per transaction, approved or rejected —
        # rejected ones pass straight through so the audit trail (and
        # processed_transactions) covers every transaction, not just approved ones.
        # Send() payloads are the *entire* input a branch sees, so channel/call_id/
        # transcript_ref must be included explicitly here or execute_node's own
        # audit entries would lose them.
        meta = _extract_meta(state)
        return [Send("execute_node", {"transaction": tx, **meta}) for tx in state["transactions"]]

    def execute_node(state: TransactionAgentState) -> dict:
        tx = dict(state["transaction"])
        meta = _extract_meta(state)

        if tx["status"] != Status.APPROVED.value:
            # Rejected (or anything else non-Approved): nothing to execute.
            return {"processed_transactions": [tx]}

        now = utcnow_iso()
        audit_entries = []
        require_legal_transition(Status(tx["status"]), Status.PROCESSING)
        tx["status"] = Status.PROCESSING.value
        tx["execution_started_at"] = now
        audit_entries.append(
            _audit_entry(tx["id"], Status.APPROVED, Status.PROCESSING, "Execution started", now, meta)
        )

        try:
            result = execute_fn(tx)
            success = bool(result.get("success"))
        except Exception as exc:
            # a broken execution for one transaction must never take down its siblings
            result = {"success": False, "simulated": True, "error": str(exc)}
            success = False

        to_status = Status.COMPLETED if success else Status.FAILED
        finish_time = utcnow_iso()
        require_legal_transition(Status.PROCESSING, to_status)
        tx["status"] = to_status.value
        tx["execution_result"] = result
        note = result.get("message") or result.get("error") or ""
        audit_entries.append(_audit_entry(tx["id"], Status.PROCESSING, to_status, note, finish_time, meta))

        return {"processed_transactions": [tx], "audit_log": audit_entries}

    def log_node(state: TransactionAgentState) -> dict:
        # reduce: runs once, after every execute_node branch has completed and
        # merged its Annotated[list, operator.add] writes into audit_log.
        # append_entries dedupes by entry_id, so this is safe to call once
        # per run even though audit_log already holds the full history.
        audit_store.append_entries(state.get("audit_log", []), path=audit_path)
        return {}

    graph = StateGraph(TransactionAgentState)
    graph.add_node("parse_node", parse_node)
    graph.add_node("resolve_recipients_node", resolve_recipients_node)
    graph.add_node("present_review_node", present_review_node)
    graph.add_node("human_approval_node", human_approval_node)
    graph.add_node("execute_node", execute_node)
    graph.add_node("log_node", log_node)

    graph.add_edge(START, "parse_node")
    graph.add_edge("parse_node", "resolve_recipients_node")
    graph.add_edge("resolve_recipients_node", "present_review_node")
    graph.add_edge("present_review_node", "human_approval_node")
    graph.add_conditional_edges("human_approval_node", route_approved, ["execute_node"])
    graph.add_edge("execute_node", "log_node")
    graph.add_edge("log_node", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
