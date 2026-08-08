"""The Transaction Agent as a LangGraph graph. Zero terminal I/O in this
module — no print(), no input(). All CLI driving lives in cli.py, so this
graph can be reused behind a different front end (a service API, a voice
agent, a watsonx Orchestrate import) later.

    parse_node -> present_review_node -> human_approval_node (interrupt)
        -> route_approved (Send fan-out, one execute_node branch per transaction: map)
            -> execute_node (Approved -> Processing -> Completed/Failed; Rejected passes through)
        -> log_node (single fan-in step over the Annotated[list, operator.add]
                      audit_log reducer once every branch has completed: reduce)

`human_approval_node` calls interrupt() as the very first thing it does and
has NO side effects before that call, because on resume LangGraph re-runs
the node from the top: the interrupt() call itself returns the resume value
instead of pausing again, and everything after it then runs exactly once.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt  # noqa: F401 (Command re-exported for cli.py convenience)

from . import audit as audit_store
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

    # branch-local input, only meaningful inside an execute_node Send() call.
    # Every parallel execute_node branch reads its own "transaction" as an
    # isolated input; none of them may return "transaction" as an output key,
    # since concurrent writes to a plain (non-Annotated) key in the same
    # superstep raise InvalidUpdateError. Only Annotated keys go back out.
    transaction: dict[str, Any]


def _audit_entry(transaction_id: str, from_status: Optional[Status], to_status: Status, note: str, timestamp: str) -> dict:
    return AuditEntry(
        transaction_id=transaction_id,
        from_status=from_status.value if from_status else None,
        to_status=to_status.value,
        timestamp=timestamp,
        note=note,
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
):
    """Compile the Transaction Agent graph.

    execute_fn: swappable (transaction_dict) -> {"success": bool, ...}. Defaults
        to the simulated executor; pass a real payment-provider call here later.
    llm_parse_fn: swappable (text) -> ParsedTransactionList. Defaults to the
        watsonx.ai structured-output parser; used unless state["offline"] is True,
        in which case the regex parser always runs regardless of this argument.
    checkpointer: defaults to InMemorySaver(). Swap for a persistent checkpointer
        (e.g. SqliteSaver) to survive process restarts across an interrupt().
    audit_path: file the persistent audit log is written to. Defaults to
        audit_store.DEFAULT_AUDIT_LOG_PATH (override for tests / multiple runs).
    """
    execute_fn = execute_fn or simulate_execution
    llm_parse_fn = llm_parse_fn or parse_with_llm
    audit_path = audit_path or audit_store.DEFAULT_AUDIT_LOG_PATH

    def parse_node(state: TransactionAgentState) -> dict:
        text = state["raw_input"]
        parsed = parse_offline(text) if state.get("offline") else llm_parse_fn(text)

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
            audit_entries.append(_audit_entry(tx.id, None, Status.CREATED, "Parsed from user input", now))

        return {"transactions": transactions, "audit_log": audit_entries}

    def present_review_node(state: TransactionAgentState) -> dict:
        now = utcnow_iso()
        updated = []
        audit_entries = []
        for tx in state["transactions"]:
            require_legal_transition(Status(tx["status"]), Status.PENDING_APPROVAL)
            tx = {**tx, "status": Status.PENDING_APPROVAL.value, "entered_queue_at": now}
            updated.append(tx)
            audit_entries.append(
                _audit_entry(tx["id"], Status.CREATED, Status.PENDING_APPROVAL, "Entered approval queue", now)
            )
        return {
            "transactions": updated,
            "review_text": _format_review(updated),
            "audit_log": audit_entries,
        }

    def human_approval_node(state: TransactionAgentState) -> dict:
        # NOTHING above this line may have a side effect: this whole node body
        # re-runs from the top when the graph is resumed after the interrupt.
        decision = interrupt(
            {
                "kind": "transaction_approval",
                "review_text": state["review_text"],
                "transactions": state["transactions"],
            }
        )

        selected_ids = set(decision.get("selected_ids") or [])
        approved_by = decision.get("approved_by") or "unknown"
        now = utcnow_iso()

        updated = []
        audit_entries = []
        for tx in state["transactions"]:
            if tx["id"] in selected_ids:
                require_legal_transition(Status(tx["status"]), Status.APPROVED)
                tx = {**tx, "status": Status.APPROVED.value, "approved_by": approved_by, "approved_at": now}
                audit_entries.append(
                    _audit_entry(tx["id"], Status.PENDING_APPROVAL, Status.APPROVED, f"approved_by={approved_by}", now)
                )
            else:
                require_legal_transition(Status(tx["status"]), Status.REJECTED)
                tx = {**tx, "status": Status.REJECTED.value}
                audit_entries.append(
                    _audit_entry(tx["id"], Status.PENDING_APPROVAL, Status.REJECTED, "Not selected for approval", now)
                )
            updated.append(tx)

        return {"transactions": updated, "audit_log": audit_entries, "approved_by": approved_by}

    def route_approved(state: TransactionAgentState):
        # map: one execute_node branch per transaction, approved or rejected —
        # rejected ones pass straight through so the audit trail (and
        # processed_transactions) covers every transaction, not just approved ones.
        return [Send("execute_node", {"transaction": tx}) for tx in state["transactions"]]

    def execute_node(state: TransactionAgentState) -> dict:
        tx = dict(state["transaction"])

        if tx["status"] != Status.APPROVED.value:
            # Rejected (or anything else non-Approved): nothing to execute.
            return {"processed_transactions": [tx]}

        now = utcnow_iso()
        audit_entries = []
        require_legal_transition(Status(tx["status"]), Status.PROCESSING)
        tx["status"] = Status.PROCESSING.value
        tx["execution_started_at"] = now
        audit_entries.append(_audit_entry(tx["id"], Status.APPROVED, Status.PROCESSING, "Execution started", now))

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
        audit_entries.append(_audit_entry(tx["id"], Status.PROCESSING, to_status, note, finish_time))

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
    graph.add_node("present_review_node", present_review_node)
    graph.add_node("human_approval_node", human_approval_node)
    graph.add_node("execute_node", execute_node)
    graph.add_node("log_node", log_node)

    graph.add_edge(START, "parse_node")
    graph.add_edge("parse_node", "present_review_node")
    graph.add_edge("present_review_node", "human_approval_node")
    graph.add_conditional_edges("human_approval_node", route_approved, ["execute_node"])
    graph.add_edge("execute_node", "log_node")
    graph.add_edge("log_node", END)

    return graph.compile(checkpointer=checkpointer or InMemorySaver())
