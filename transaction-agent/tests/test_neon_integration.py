"""Opt-in integration tests against a real Neon Postgres database — skipped
entirely unless DATABASE_URL / DATABASE_URL_DIRECT are configured (they are
not required for the rest of the suite, which stays fully offline via
SQLite/JSON). These exist because the dual-backend design in audit.py /
recipient_directory.py / users.py / transaction_agent/db.py is only really
proven by hitting the real thing — Neon's pooled endpoint in particular
had a real, non-obvious bug (session state like `SET search_path` silently
dropped across statements under PgBouncer transaction pooling) that no
amount of local SQLite testing could have caught.

Unlike the rest of the suite, these tests intentionally do NOT clear the
shared Neon tables (other real usage — the CLI, manual verification runs —
lives in the same database) — every row they create uses a uuid-suffixed
identifier so it can't collide with or be mistaken for real data.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_DIRECT = os.environ.get("DATABASE_URL_DIRECT")

pytestmark = pytest.mark.skipif(
    not (DATABASE_URL and DATABASE_URL_DIRECT),
    reason="DATABASE_URL / DATABASE_URL_DIRECT not configured — set them in .env to run Neon integration tests",
)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def test_audit_postgres_backend_dedupes_and_reads_back():
    from transaction_agent import audit

    tx_id = f"txn_{_uid()}"
    e1 = {
        "entry_id": f"e_{_uid()}",
        "transaction_id": tx_id,
        "from_status": None,
        "to_status": "Created",
        "timestamp": "2026-01-01T00:00:00Z",
        "note": "integration test",
        "channel": "test",
        "call_id": None,
        "transcript_ref": None,
    }
    fresh = audit.append_entries([e1], DATABASE_URL)
    assert len(fresh) == 1
    fresh_again = audit.append_entries([e1], DATABASE_URL)
    assert fresh_again == []

    all_entries = audit.read_all(DATABASE_URL)
    matching = [e for e in all_entries if e["transaction_id"] == tx_id]
    assert len(matching) == 1
    assert matching[0]["entry_id"] == e1["entry_id"]


def test_recipient_directory_postgres_backend_register_and_resolve():
    from transaction_agent import recipient_directory as rd

    name = f"Integration Test Vendor {_uid()}"
    recipient_id = rd.register(name, path=DATABASE_URL)
    assert recipient_id.startswith("rcpt_")

    names = {r["name"] for r in rd.list_all(path=DATABASE_URL)}
    assert name in names

    resolution = rd.resolve(name, path=DATABASE_URL)
    assert resolution.status == "auto"
    assert resolution.recipient_id == recipient_id


def test_users_postgres_backend_create_and_verify():
    from transaction_agent import users

    username = f"itest_{_uid()}"
    users.create_user(username, "correct-horse", path=DATABASE_URL)
    assert users.verify(username, "correct-horse", path=DATABASE_URL) is True
    assert users.verify(username, "wrong", path=DATABASE_URL) is False
    assert users.user_exists(username, path=DATABASE_URL) is True
    assert users.user_exists(f"nobody_{_uid()}", path=DATABASE_URL) is False


def test_full_graph_flow_against_neon():
    from langgraph.types import Command

    from transaction_agent import recipient_directory as rd
    from transaction_agent import users
    from transaction_agent.checkpointer import open_checkpointer
    from transaction_agent.graph import build_graph

    username = f"itest_{_uid()}"
    users.create_user(username, "hunter2", path=DATABASE_URL)
    vendor_name = f"Integration Vendor {_uid()}"
    rd.register(vendor_name, path=DATABASE_URL)

    conn, saver = open_checkpointer("unused.sqlite", postgres_dsn=DATABASE_URL_DIRECT)
    try:
        graph = build_graph(
            checkpointer=saver, audit_path=DATABASE_URL, recipient_directory_path=DATABASE_URL, users_path=DATABASE_URL
        )
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = graph.invoke(
            {
                "raw_input": f"Pay 42 to {vendor_name}",
                "offline": True,
                "channel": "test",
                "transactions": [],
                "audit_log": [],
                "processed_transactions": [],
            },
            config=config,
        )
        tx = out["__interrupt__"][0].value["transactions"][0]
        assert tx["recipient_id"] is not None  # exact match auto-resolved

        final = graph.invoke(
            Command(resume={"selected_ids": [tx["id"]], "username": username, "passphrase": "hunter2"}),
            config=config,
        )
        assert final["processed_transactions"][0]["status"] == "Completed"
    finally:
        conn.close()


def test_checkpoint_persists_across_a_fresh_connection_to_neon():
    from langgraph.types import Command

    from transaction_agent import recipient_directory as rd
    from transaction_agent import users
    from transaction_agent.checkpointer import open_checkpointer
    from transaction_agent.graph import build_graph

    username = f"itest_{_uid()}"
    users.create_user(username, "hunter2", path=DATABASE_URL)
    vendor_name = f"Integration Vendor {_uid()}"
    rd.register(vendor_name, path=DATABASE_URL)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    conn1, saver1 = open_checkpointer("unused.sqlite", postgres_dsn=DATABASE_URL_DIRECT)
    try:
        graph1 = build_graph(
            checkpointer=saver1, audit_path=DATABASE_URL, recipient_directory_path=DATABASE_URL, users_path=DATABASE_URL
        )
        out = graph1.invoke(
            {
                "raw_input": f"Pay 7 to {vendor_name}",
                "offline": True,
                "transactions": [],
                "audit_log": [],
                "processed_transactions": [],
            },
            config=config,
        )
        assert "__interrupt__" in out
    finally:
        conn1.close()

    # a completely fresh connection + graph object, simulating a process restart
    conn2, saver2 = open_checkpointer("unused.sqlite", postgres_dsn=DATABASE_URL_DIRECT)
    try:
        graph2 = build_graph(
            checkpointer=saver2, audit_path=DATABASE_URL, recipient_directory_path=DATABASE_URL, users_path=DATABASE_URL
        )
        snapshot = graph2.get_state(config)
        pending = [i for task in snapshot.tasks for i in task.interrupts]
        assert len(pending) == 1
        tx = pending[0].value["transactions"][0]

        final = graph2.invoke(
            Command(resume={"selected_ids": [tx["id"]], "username": username, "passphrase": "hunter2"}),
            config=config,
        )
        assert final["processed_transactions"][0]["status"] == "Completed"
    finally:
        conn2.close()
