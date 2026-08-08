#!/usr/bin/env python3
"""HTTP front end for the Transaction Agent graph — a second, non-terminal
front end alongside cli.py, meant for a future voice agent (or any other
non-interactive caller) to drive.

Run it with:

    uvicorn api:app --reload

The graph module (transaction_agent/graph.py) is untouched by this file: it
is called exactly the way cli.py calls it — graph.invoke(...) for the first
step, Command(resume=...) to advance past an interrupt, graph.get_state(...)
to peek what a thread is currently waiting on.

One extension not covered by the endpoints spec: recipient-disambiguation
interrupts. There's no dedicated endpoint for a caller to answer "which
recipient did you mean" mid-request, so POST /requests auto-resolves any
recipient_disambiguation interrupt(s) itself (top-scored candidate for an
ambiguous match, register-new for no match) before returning the review to
the caller. See _auto_resolve_recipients() below and the README's
"Orchestrate readiness" section for why this is safe and where a future
phase could add a proper endpoint for it instead.

Every request builds its own graph + SQLite checkpoint connection (see
get_graph()) and closes it when the request finishes. This is deliberate,
not just convenient: build_graph() has no global mutable state (see the
README), so two concurrent requests never share a connection object, and
the pattern doubles as a live demonstration that build_graph() is safe to
call fresh per call site — the property the Orchestrate readiness pass
needed to confirm.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, status
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel

from transaction_agent import audit as audit_store
from transaction_agent import recipient_directory
from transaction_agent import users as users_store
from transaction_agent.graph import build_graph
from transaction_agent.models import AuditEntry, Transaction

load_dotenv()

DEFAULT_DEV_API_KEY = "dev-local-key"


@dataclass
class Settings:
    checkpoint_db: str = "checkpoints.sqlite"
    audit_path: str = field(default_factory=lambda: audit_store.DEFAULT_AUDIT_LOG_PATH)
    recipient_directory_path: str = field(default_factory=lambda: recipient_directory.DEFAULT_DIRECTORY_PATH)
    users_path: str = field(default_factory=lambda: users_store.DEFAULT_USERS_PATH)
    api_key: str = field(default_factory=lambda: os.environ.get("TRANSACTION_AGENT_API_KEY", DEFAULT_DEV_API_KEY))
    offline: bool = field(
        default_factory=lambda: os.environ.get("TRANSACTION_AGENT_OFFLINE", "").lower() in ("1", "true", "yes")
    )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            checkpoint_db=os.environ.get("CHECKPOINT_DB_PATH", "checkpoints.sqlite"),
            audit_path=os.environ.get("AUDIT_LOG_PATH", audit_store.DEFAULT_AUDIT_LOG_PATH),
            recipient_directory_path=os.environ.get(
                "RECIPIENT_DIRECTORY_PATH", recipient_directory.DEFAULT_DIRECTORY_PATH
            ),
            users_path=os.environ.get("USERS_DB_PATH", users_store.DEFAULT_USERS_PATH),
            api_key=os.environ.get("TRANSACTION_AGENT_API_KEY", DEFAULT_DEV_API_KEY),
            offline=os.environ.get("TRANSACTION_AGENT_OFFLINE", "").lower() in ("1", "true", "yes"),
        )


# --- request/response models --------------------------------------------


class CreateRequestBody(BaseModel):
    raw_request: str
    requester_id: str


class CreateRequestResponse(BaseModel):
    thread_id: str
    review_text: str
    transactions: list[Transaction]


class ApproveBody(BaseModel):
    selected_ids: list[str]
    approver_id: str
    passphrase: str


class ApproveResponse(BaseModel):
    thread_id: str
    results: list[Transaction]


class ThreadStateResponse(BaseModel):
    thread_id: str
    status: str  # "pending_recipient_disambiguation" | "pending_approval" | "completed"
    review_text: Optional[str] = None
    transactions: Optional[list[Transaction]] = None
    pending_recipients: Optional[list[dict[str, Any]]] = None
    error: Optional[str] = None
    results: Optional[list[Transaction]] = None


class AuditResponse(BaseModel):
    transaction_id: str
    entries: list[AuditEntry]


# --- app factory ----------------------------------------------------------


def _initial_state(raw_request: str, requester_id: str, offline: bool) -> dict:
    return {
        "raw_input": raw_request,
        # not consumed by the graph today (graph.py is unchanged this phase);
        # carried on the state dict so a future graph revision can use it
        # without an API contract change.
        "requester_id": requester_id,
        "offline": offline,
        "transactions": [],
        "audit_log": [],
        "processed_transactions": [],
    }


def _auto_resolve_recipients(graph, config, interrupts) -> dict:
    """Advance past any recipient_disambiguation interrupt(s) with a
    deterministic default policy, since this API has no endpoint for a
    caller to answer that question mid-request. Returns the
    transaction_approval interrupt payload once reached."""
    while interrupts:
        payload = interrupts[0].value
        if payload["kind"] != "recipient_disambiguation":
            return payload
        choices = {}
        for item in payload["pending"]:
            if item["status"] == "ambiguous" and item["candidates"]:
                choices[item["transaction_id"]] = {"recipient_id": item["candidates"][0]["recipient_id"]}
            else:
                choices[item["transaction_id"]] = {"register_new": {"name": item["recipient_text"]}}
        state = graph.invoke(Command(resume={"choices": choices}), config=config)
        interrupts = state.get("__interrupt__")
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Graph completed without reaching an approval gate")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Transaction Agent API", version="0.3.0")
    app.state.settings = settings

    def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
        if not x_api_key or x_api_key != settings.api_key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")

    def get_graph():
        conn = sqlite3.connect(settings.checkpoint_db, check_same_thread=False)
        try:
            saver = SqliteSaver(conn)
            saver.setup()
            yield build_graph(
                checkpointer=saver,
                audit_path=settings.audit_path,
                recipient_directory_path=settings.recipient_directory_path,
                users_path=settings.users_path,
            )
        finally:
            conn.close()

    auth = Depends(require_api_key)

    @app.post("/requests", response_model=CreateRequestResponse, dependencies=[auth])
    def create_request(body: CreateRequestBody, graph=Depends(get_graph)):
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        state = graph.invoke(
            _initial_state(body.raw_request, body.requester_id, settings.offline), config=config
        )
        interrupts = state.get("__interrupt__")
        if not interrupts:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Graph completed without pausing for approval")

        payload = _auto_resolve_recipients(graph, config, interrupts)
        return CreateRequestResponse(
            thread_id=thread_id,
            review_text=payload["review_text"],
            transactions=[Transaction(**t) for t in payload["transactions"]],
        )

    @app.post("/requests/{thread_id}/approve", response_model=ApproveResponse, dependencies=[auth])
    def approve_request(thread_id: str, body: ApproveBody, graph=Depends(get_graph)):
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        pending = [i for task in snapshot.tasks for i in task.interrupts]

        if not pending:
            if not snapshot.values:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown thread {thread_id!r}")
            raise HTTPException(status.HTTP_409_CONFLICT, f"Thread {thread_id!r} has already completed")

        if pending[0].value["kind"] != "transaction_approval":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Thread {thread_id!r} is waiting on {pending[0].value['kind']!r}, not approval",
            )

        resume_value = {
            "selected_ids": body.selected_ids,
            "username": body.approver_id,
            "passphrase": body.passphrase,
        }
        state = graph.invoke(Command(resume=resume_value), config=config)
        interrupts = state.get("__interrupt__")
        if interrupts:
            # human_approval_node paused again in its retry loop — the
            # passphrase didn't verify. Nothing was approved.
            payload = interrupts[0].value
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, payload.get("error") or "Approval was not accepted")

        return ApproveResponse(
            thread_id=thread_id,
            results=[Transaction(**t) for t in state["processed_transactions"]],
        )

    @app.get("/requests/{thread_id}", response_model=ThreadStateResponse, dependencies=[auth])
    def get_request_state(thread_id: str, graph=Depends(get_graph)):
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        if not snapshot.values:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown thread {thread_id!r}")

        pending = [i for task in snapshot.tasks for i in task.interrupts]
        if not pending:
            results = snapshot.values.get("processed_transactions", [])
            return ThreadStateResponse(
                thread_id=thread_id,
                status="completed",
                results=[Transaction(**t) for t in results],
            )

        payload = pending[0].value
        if payload["kind"] == "recipient_disambiguation":
            return ThreadStateResponse(
                thread_id=thread_id,
                status="pending_recipient_disambiguation",
                pending_recipients=payload["pending"],
            )
        return ThreadStateResponse(
            thread_id=thread_id,
            status="pending_approval",
            review_text=payload.get("review_text"),
            transactions=[Transaction(**t) for t in payload.get("transactions", [])],
            error=payload.get("error"),
        )

    @app.get("/audit/{transaction_id}", response_model=AuditResponse, dependencies=[auth])
    def get_audit(transaction_id: str):
        entries = [e for e in audit_store.read_all(settings.audit_path) if e["transaction_id"] == transaction_id]
        if not entries:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No audit entries for transaction {transaction_id!r}")
        return AuditResponse(transaction_id=transaction_id, entries=[AuditEntry(**e) for e in entries])

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
