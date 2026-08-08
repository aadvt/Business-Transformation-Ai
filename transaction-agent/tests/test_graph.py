import uuid

from langgraph.types import Command

from transaction_agent import audit, recipient_directory, users
from transaction_agent.graph import build_graph


def _paths(tmp_path):
    return {
        "audit_path": str(tmp_path / "audit.json"),
        "recipient_directory_path": str(tmp_path / "recipients.sqlite"),
        "users_path": str(tmp_path / "users.sqlite"),
    }


def _seed_user(paths, username="krish", passphrase="hunter2"):
    users.create_user(username, passphrase, path=paths["users_path"])


def _seed_recipients(paths, names):
    """Register exact-name recipients so resolve_recipients_node auto-resolves
    them without a disambiguation interrupt — keeps approval-flow tests
    focused on the approval gate rather than recipient matching."""
    for name in names:
        recipient_directory.register(name, path=paths["recipient_directory_path"])


def _initial_state(text: str) -> dict:
    return {
        "raw_input": text,
        "offline": True,
        "transactions": [],
        "audit_log": [],
        "processed_transactions": [],
    }


def _start(graph, text: str):
    """Invoke and expect the first (and, with seeded recipients, only)
    interrupt to be the transaction_approval gate."""
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke(_initial_state(text), config=config)
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "transaction_approval"
    return config, payload["transactions"]


def _approve(graph, config, selected_ids, username="krish", passphrase="hunter2"):
    return graph.invoke(
        Command(resume={"selected_ids": selected_ids, "username": username, "passphrase": passphrase}),
        config=config,
    )


def test_full_approval_flow_completes_and_persists(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    _seed_recipients(paths, ["ABC Logistics", "Ravi Transport"])
    graph = build_graph(**paths)

    config, transactions = _start(graph, "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport")
    ids = [t["id"] for t in transactions]

    final = _approve(graph, config, ids)

    statuses = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    assert statuses == {"ABC Logistics": "Completed", "Ravi Transport": "Completed"}
    assert all(t["approved_by"] == "krish" for t in final["processed_transactions"])
    assert all(t["recipient_id"] for t in final["processed_transactions"])
    assert len(audit.read_all(paths["audit_path"])) == 12  # 2 recipient-resolution notes + 5x2 transitions


def test_unselected_transactions_are_rejected_not_silently_dropped(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    _seed_recipients(paths, ["A", "B", "C"])
    graph = build_graph(**paths)

    config, transactions = _start(graph, "Pay 100 to A, 200 to B, 300 to C")
    ids = [t["id"] for t in transactions]

    final = _approve(graph, config, [ids[0]])

    processed = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    assert set(processed) == {"A", "B", "C"}
    assert processed["A"] == "Completed"
    assert processed["B"] == "Rejected"
    assert processed["C"] == "Rejected"


def test_audit_entries_not_duplicated_by_interrupt_resume(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    _seed_recipients(paths, ["A"])
    graph = build_graph(**paths)

    config, transactions = _start(graph, "Pay 100 to A")
    tx_id = transactions[0]["id"]

    final = _approve(graph, config, [tx_id])

    entries = final["audit_log"]
    entry_ids = [e["entry_id"] for e in entries]
    assert len(entry_ids) == len(set(entry_ids)), "duplicate audit entries after resume"
    # recipient-resolved note, Created, PendingApproval, Approved, Processing, Completed
    assert len(entries) == 6

    persisted = audit.read_all(paths["audit_path"])
    persisted_ids = [e["entry_id"] for e in persisted]
    assert len(persisted_ids) == len(set(persisted_ids)), "duplicate persisted audit entries"
    assert len(persisted) == 6


def test_execution_failure_does_not_affect_siblings(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    _seed_recipients(paths, ["ABC Logistics", "Ravi Transport", "Zed Co"])

    def flaky_execute(tx):
        if tx["recipient"] == "Ravi Transport":
            raise RuntimeError("simulated provider outage")
        return {"success": True, "message": "ok"}

    graph = build_graph(execute_fn=flaky_execute, **paths)
    config, transactions = _start(graph, "Pay 100 to ABC Logistics, 200 to Ravi Transport, 300 to Zed Co")
    ids = [t["id"] for t in transactions]

    final = _approve(graph, config, ids)

    statuses = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    assert statuses["ABC Logistics"] == "Completed"
    assert statuses["Zed Co"] == "Completed"
    assert statuses["Ravi Transport"] == "Failed"

    failed_tx = next(t for t in final["processed_transactions"] if t["recipient"] == "Ravi Transport")
    assert "simulated provider outage" in failed_tx["execution_result"]["error"]


def test_execute_fn_returning_failure_is_recorded_without_raising(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    _seed_recipients(paths, ["A"])

    def always_fails(tx):
        return {"success": False, "message": "insufficient funds"}

    graph = build_graph(execute_fn=always_fails, **paths)
    config, transactions = _start(graph, "Pay 100 to A")
    ids = [t["id"] for t in transactions]

    final = _approve(graph, config, ids)
    tx = final["processed_transactions"][0]
    assert tx["status"] == "Failed"
    assert tx["execution_result"]["message"] == "insufficient funds"


def test_empty_input_completes_without_transactions(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    graph = build_graph(**paths)

    config, transactions = _start(graph, "hello there, nothing to pay here")
    assert transactions == []

    final = _approve(graph, config, [])
    assert final["processed_transactions"] == []
    assert audit.read_all(paths["audit_path"]) == []


def test_ambiguous_recipient_triggers_disambiguation_interrupt(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    recipient_directory.register("Ravi Transport Services", path=paths["recipient_directory_path"])
    recipient_directory.register("Ravi Traders", path=paths["recipient_directory_path"])
    graph = build_graph(**paths)

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke(_initial_state("Pay 500 to Ravi Trans"), config=config)

    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "recipient_disambiguation"
    pending = payload["pending"]
    assert len(pending) == 1
    assert pending[0]["status"] == "ambiguous"
    candidate_ids = {c["recipient_id"] for c in pending[0]["candidates"]}
    assert len(candidate_ids) == 2
    tx_id = pending[0]["transaction_id"]

    chosen_id = pending[0]["candidates"][0]["recipient_id"]
    out2 = graph.invoke(Command(resume={"choices": {tx_id: {"recipient_id": chosen_id}}}), config=config)

    approval_payload = out2["__interrupt__"][0].value
    assert approval_payload["kind"] == "transaction_approval"
    resolved_tx = approval_payload["transactions"][0]
    assert resolved_tx["recipient_id"] == chosen_id

    final = _approve(graph, config, [resolved_tx["id"]])
    assert final["processed_transactions"][0]["recipient_id"] == chosen_id


def test_unknown_recipient_can_be_registered_via_interrupt(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    graph = build_graph(**paths)

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke(_initial_state("Pay 500 to Brand New Vendor"), config=config)
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "recipient_disambiguation"
    tx_id = payload["pending"][0]["transaction_id"]
    assert payload["pending"][0]["status"] == "none"

    out2 = graph.invoke(
        Command(resume={"choices": {tx_id: {"register_new": {"name": "Brand New Vendor", "notes": "first payment"}}}}),
        config=config,
    )
    approval_payload = out2["__interrupt__"][0].value
    resolved_tx = approval_payload["transactions"][0]
    assert resolved_tx["recipient_id"] is not None
    assert resolved_tx["recipient_id"].startswith("rcpt_")

    directory_entries = recipient_directory.list_all(paths["recipient_directory_path"])
    assert any(
        e["recipient_id"] == resolved_tx["recipient_id"] and e["name"] == "Brand New Vendor" for e in directory_entries
    )


def test_unresolved_recipient_left_blank_still_proceeds(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths)
    graph = build_graph(**paths)

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke(_initial_state("Pay 500 to Nobody Knows"), config=config)
    tx_id = out["__interrupt__"][0].value["pending"][0]["transaction_id"]

    out2 = graph.invoke(Command(resume={"choices": {}}), config=config)
    resolved_tx = out2["__interrupt__"][0].value["transactions"][0]
    assert resolved_tx["id"] == tx_id
    assert resolved_tx["recipient_id"] is None


def test_bad_passphrase_is_rejected_and_reprompts_without_recording_approval(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths, username="krish", passphrase="hunter2")
    _seed_recipients(paths, ["A"])
    graph = build_graph(**paths)

    config, transactions = _start(graph, "Pay 100 to A")
    tx_id = transactions[0]["id"]

    bad = graph.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "WRONG"}),
        config=config,
    )
    payload = bad["__interrupt__"][0].value
    assert payload["kind"] == "transaction_approval"
    assert "Authentication failed" in payload["error"]

    # nothing was approved yet — the transaction is still sitting in PendingApproval
    still_pending = payload["transactions"][0]
    assert still_pending["status"] == "PendingApproval"
    assert still_pending["approved_by"] is None

    also_bad = graph.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "someone-else", "passphrase": "nope"}),
        config=config,
    )
    assert "Authentication failed for 'someone-else'" in also_bad["__interrupt__"][0].value["error"]

    final = _approve(graph, config, [tx_id])
    assert final["processed_transactions"][0]["approved_by"] == "krish"
    assert final["processed_transactions"][0]["status"] == "Completed"


def test_unknown_username_is_rejected(tmp_path):
    paths = _paths(tmp_path)
    _seed_user(paths, username="krish", passphrase="hunter2")
    _seed_recipients(paths, ["A"])
    graph = build_graph(**paths)

    config, transactions = _start(graph, "Pay 100 to A")
    tx_id = transactions[0]["id"]

    out = graph.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "ghost", "passphrase": "hunter2"}),
        config=config,
    )
    assert "Authentication failed for 'ghost'" in out["__interrupt__"][0].value["error"]
