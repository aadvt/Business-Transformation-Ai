import uuid

from langgraph.types import Command

from transaction_agent import audit
from transaction_agent.graph import build_graph


def _initial_state(text: str) -> dict:
    return {
        "raw_input": text,
        "offline": True,
        "transactions": [],
        "audit_log": [],
        "processed_transactions": [],
    }


def _start(graph, text: str):
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    out = graph.invoke(_initial_state(text), config=config)
    interrupt_payload = out["__interrupt__"][0].value
    return config, interrupt_payload["transactions"]


def test_full_approval_flow_completes_and_persists(tmp_path):
    audit_path = str(tmp_path / "audit.json")
    graph = build_graph(audit_path=audit_path)

    config, transactions = _start(graph, "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport")
    ids = [t["id"] for t in transactions]

    final = graph.invoke(Command(resume={"selected_ids": ids, "approved_by": "krish"}), config=config)

    statuses = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    assert statuses == {"ABC Logistics": "Completed", "Ravi Transport": "Completed"}
    assert len(audit.read_all(audit_path)) == 10  # 5 transitions x 2 transactions


def test_unselected_transactions_are_rejected_not_silently_dropped(tmp_path):
    audit_path = str(tmp_path / "audit.json")
    graph = build_graph(audit_path=audit_path)

    config, transactions = _start(graph, "Pay 100 to A, 200 to B, 300 to C")
    ids = [t["id"] for t in transactions]

    # only approve the first
    final = graph.invoke(Command(resume={"selected_ids": [ids[0]], "approved_by": "krish"}), config=config)

    processed = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    # all three must be present in the output, not just the approved one
    assert set(processed) == {"A", "B", "C"}
    assert processed["A"] == "Completed"
    assert processed["B"] == "Rejected"
    assert processed["C"] == "Rejected"


def test_audit_entries_not_duplicated_by_interrupt_resume(tmp_path):
    audit_path = str(tmp_path / "audit.json")
    graph = build_graph(audit_path=audit_path)

    config, transactions = _start(graph, "Pay 100 to A")
    tx_id = transactions[0]["id"]

    final = graph.invoke(Command(resume={"selected_ids": [tx_id], "approved_by": "krish"}), config=config)

    entries = final["audit_log"]
    entry_ids = [e["entry_id"] for e in entries]
    assert len(entry_ids) == len(set(entry_ids)), "duplicate audit entries after resume"
    # Created, PendingApproval, Approved, Processing, Completed
    assert len(entries) == 5

    persisted = audit.read_all(audit_path)
    persisted_ids = [e["entry_id"] for e in persisted]
    assert len(persisted_ids) == len(set(persisted_ids)), "duplicate persisted audit entries"
    assert len(persisted) == 5


def test_execution_failure_does_not_affect_siblings(tmp_path):
    audit_path = str(tmp_path / "audit.json")

    def flaky_execute(tx):
        if tx["recipient"] == "Ravi Transport":
            raise RuntimeError("simulated provider outage")
        return {"success": True, "message": "ok"}

    graph = build_graph(execute_fn=flaky_execute, audit_path=audit_path)
    config, transactions = _start(graph, "Pay 100 to ABC Logistics, 200 to Ravi Transport, 300 to Zed Co")
    ids = [t["id"] for t in transactions]

    final = graph.invoke(Command(resume={"selected_ids": ids, "approved_by": "krish"}), config=config)

    statuses = {t["recipient"]: t["status"] for t in final["processed_transactions"]}
    assert statuses["ABC Logistics"] == "Completed"
    assert statuses["Zed Co"] == "Completed"
    assert statuses["Ravi Transport"] == "Failed"

    failed_tx = next(t for t in final["processed_transactions"] if t["recipient"] == "Ravi Transport")
    assert "simulated provider outage" in failed_tx["execution_result"]["error"]


def test_execute_fn_returning_failure_is_recorded_without_raising(tmp_path):
    audit_path = str(tmp_path / "audit.json")

    def always_fails(tx):
        return {"success": False, "message": "insufficient funds"}

    graph = build_graph(execute_fn=always_fails, audit_path=audit_path)
    config, transactions = _start(graph, "Pay 100 to A")
    ids = [t["id"] for t in transactions]

    final = graph.invoke(Command(resume={"selected_ids": ids, "approved_by": "krish"}), config=config)
    tx = final["processed_transactions"][0]
    assert tx["status"] == "Failed"
    assert tx["execution_result"]["message"] == "insufficient funds"


def test_empty_input_completes_without_transactions(tmp_path):
    audit_path = str(tmp_path / "audit.json")
    graph = build_graph(audit_path=audit_path)

    config, transactions = _start(graph, "hello there, nothing to pay here")
    assert transactions == []

    final = graph.invoke(Command(resume={"selected_ids": [], "approved_by": "krish"}), config=config)
    assert final["processed_transactions"] == []
    assert audit.read_all(audit_path) == []
