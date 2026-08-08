"""Durable checkpointing: a paused approval must survive the process
restarting, as long as the SQLite checkpoint file is on disk. We simulate a
restart by discarding the in-memory connection/graph and building fresh
ones pointed at the same file — nothing here reuses in-process state.
"""

import sqlite3
import uuid

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from transaction_agent import recipient_directory, users
from transaction_agent.graph import build_graph


def _open_graph(checkpoint_path, **build_kwargs):
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    graph = build_graph(checkpointer=saver, **build_kwargs)
    return conn, graph


def _initial_state(text: str) -> dict:
    return {
        "raw_input": text,
        "offline": True,
        "transactions": [],
        "audit_log": [],
        "processed_transactions": [],
    }


def test_persisted_thread_resumes_after_simulated_restart(tmp_path):
    checkpoint_path = str(tmp_path / "checkpoints.sqlite")
    build_kwargs = {
        "audit_path": str(tmp_path / "audit.json"),
        "recipient_directory_path": str(tmp_path / "recipients.sqlite"),
        "users_path": str(tmp_path / "users.sqlite"),
    }
    users.create_user("krish", "hunter2", path=build_kwargs["users_path"])

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # --- "process 1": start the request, pause at recipient disambiguation ---
    conn1, graph1 = _open_graph(checkpoint_path, **build_kwargs)
    out = graph1.invoke(_initial_state("Pay 500 to Some New Vendor"), config=config)
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "recipient_disambiguation"
    tx_id = payload["pending"][0]["transaction_id"]
    conn1.close()  # simulate the process exiting

    # --- "process 2": fresh connection + fresh graph object, same file ---
    conn2, graph2 = _open_graph(checkpoint_path, **build_kwargs)
    snapshot = graph2.get_state(config)
    pending_interrupts = [i for task in snapshot.tasks for i in task.interrupts]
    assert len(pending_interrupts) == 1
    assert pending_interrupts[0].value["kind"] == "recipient_disambiguation"
    assert pending_interrupts[0].value["pending"][0]["transaction_id"] == tx_id

    out2 = graph2.invoke(
        Command(resume={"choices": {tx_id: {"register_new": {"name": "Some New Vendor"}}}}),
        config=config,
    )
    approval_payload = out2["__interrupt__"][0].value
    assert approval_payload["kind"] == "transaction_approval"
    conn2.close()

    # --- "process 3": another fresh connection to finish the approval ---
    conn3, graph3 = _open_graph(checkpoint_path, **build_kwargs)
    final = graph3.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "hunter2"}),
        config=config,
    )
    conn3.close()

    assert final["processed_transactions"][0]["status"] == "Completed"
    assert final["processed_transactions"][0]["recipient_id"] is not None
    directory = recipient_directory.list_all(build_kwargs["recipient_directory_path"])
    assert any(e["name"] == "Some New Vendor" for e in directory)


def test_failed_passphrase_attempt_survives_restart_before_retry(tmp_path):
    checkpoint_path = str(tmp_path / "checkpoints.sqlite")
    build_kwargs = {
        "audit_path": str(tmp_path / "audit.json"),
        "recipient_directory_path": str(tmp_path / "recipients.sqlite"),
        "users_path": str(tmp_path / "users.sqlite"),
    }
    users.create_user("krish", "hunter2", path=build_kwargs["users_path"])
    recipient_directory.register("A", path=build_kwargs["recipient_directory_path"])

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    conn1, graph1 = _open_graph(checkpoint_path, **build_kwargs)
    out = graph1.invoke(_initial_state("Pay 100 to A"), config=config)
    tx_id = out["__interrupt__"][0].value["transactions"][0]["id"]

    bad = graph1.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "WRONG"}),
        config=config,
    )
    assert "Authentication failed" in bad["__interrupt__"][0].value["error"]
    conn1.close()

    # fresh process, correct passphrase this time
    conn2, graph2 = _open_graph(checkpoint_path, **build_kwargs)
    final = graph2.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "hunter2"}),
        config=config,
    )
    conn2.close()

    assert final["processed_transactions"][0]["status"] == "Completed"
    assert final["processed_transactions"][0]["approved_by"] == "krish"
