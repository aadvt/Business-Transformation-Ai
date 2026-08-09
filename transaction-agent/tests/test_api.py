import pathlib

from fastapi.testclient import TestClient

from api import Settings, create_app
from transaction_agent import recipient_directory, users


def _settings(tmp_path: pathlib.Path, **overrides) -> Settings:
    defaults = dict(
        checkpoint_db=str(tmp_path / "checkpoints.sqlite"),
        checkpoint_dsn=None,  # force SQLite even if DATABASE_URL_DIRECT is set in the environment
        audit_path=str(tmp_path / "audit.json"),
        recipient_directory_path=str(tmp_path / "recipients.sqlite"),
        users_path=str(tmp_path / "users.sqlite"),
        api_key="test-key",
        offline=True,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _seed(settings: Settings, recipients=(), username="krish", passphrase="hunter2"):
    users.create_user(username, passphrase, path=settings.users_path)
    for name in recipients:
        recipient_directory.register(name, path=settings.recipient_directory_path)


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


HEADERS = {"X-API-Key": "test-key"}


def test_missing_api_key_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    client = _client(settings)

    r = client.post("/requests", json={"raw_request": "Pay 100 to A", "requester_id": "u1"})
    assert r.status_code == 401


def test_wrong_api_key_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    client = _client(settings)

    r = client.post(
        "/requests",
        json={"raw_request": "Pay 100 to A", "requester_id": "u1"},
        headers={"X-API-Key": "not-the-right-key"},
    )
    assert r.status_code == 401


def test_full_happy_path_through_requests_and_approve(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, recipients=["ABC Logistics", "Ravi Transport"])
    client = _client(settings)

    create = client.post(
        "/requests",
        json={"raw_request": "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport", "requester_id": "u1"},
        headers=HEADERS,
    )
    assert create.status_code == 200
    body = create.json()
    thread_id = body["thread_id"]
    assert len(body["transactions"]) == 2
    assert "20,500.00" in body["review_text"]
    ids = [t["id"] for t in body["transactions"]]
    assert all(t["recipient_id"] for t in body["transactions"])  # exact matches auto-resolved

    approve = client.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": ids, "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    assert approve.status_code == 200
    results = approve.json()["results"]
    assert {r["status"] for r in results} == {"Completed"}
    assert all(r["approved_by"] == "krish" for r in results)

    state = client.get(f"/requests/{thread_id}", headers=HEADERS)
    assert state.status_code == 200
    assert state.json()["status"] == "completed"

    audit = client.get(f"/audit/{ids[0]}", headers=HEADERS)
    assert audit.status_code == 200
    assert len(audit.json()["entries"]) > 0


def test_partial_selection_rejects_unselected_not_dropped(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, recipients=["A", "B"])
    client = _client(settings)

    create = client.post(
        "/requests", json={"raw_request": "Pay 100 to A, 200 to B", "requester_id": "u1"}, headers=HEADERS
    )
    ids = [t["id"] for t in create.json()["transactions"]]

    approve = client.post(
        f"/requests/{create.json()['thread_id']}/approve",
        json={"selected_ids": [ids[0]], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    results = {r["recipient"]: r["status"] for r in approve.json()["results"]}
    assert results == {"A": "Completed", "B": "Rejected"}


def test_wrong_passphrase_is_rejected_with_clear_error(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, recipients=["A"])
    client = _client(settings)

    create = client.post("/requests", json={"raw_request": "Pay 100 to A", "requester_id": "u1"}, headers=HEADERS)
    thread_id = create.json()["thread_id"]
    tx_id = create.json()["transactions"][0]["id"]

    bad = client.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": [tx_id], "approver_id": "krish", "passphrase": "WRONG"},
        headers=HEADERS,
    )
    assert bad.status_code == 401
    assert "Authentication failed" in bad.json()["detail"]

    # nothing was recorded — the thread is still waiting on approval
    state = client.get(f"/requests/{thread_id}", headers=HEADERS)
    assert state.json()["status"] == "pending_approval"

    # and a correct retry still works afterwards
    good = client.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": [tx_id], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    assert good.status_code == 200
    assert good.json()["results"][0]["status"] == "Completed"


def test_unknown_thread_returns_404(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)
    client = _client(settings)

    r = client.get("/requests/does-not-exist", headers=HEADERS)
    assert r.status_code == 404

    r2 = client.post(
        "/requests/does-not-exist/approve",
        json={"selected_ids": [], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    assert r2.status_code == 404


def test_approving_an_already_completed_thread_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, recipients=["A"])
    client = _client(settings)

    create = client.post("/requests", json={"raw_request": "Pay 100 to A", "requester_id": "u1"}, headers=HEADERS)
    thread_id = create.json()["thread_id"]
    tx_id = create.json()["transactions"][0]["id"]
    client.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": [tx_id], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )

    again = client.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": [tx_id], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    assert again.status_code == 409


def test_recipient_disambiguation_is_auto_resolved(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings)  # no recipients registered -> forces auto-register
    client = _client(settings)

    create = client.post(
        "/requests", json={"raw_request": "Pay 500 to Brand New Vendor", "requester_id": "u1"}, headers=HEADERS
    )
    assert create.status_code == 200
    tx = create.json()["transactions"][0]
    assert tx["recipient_id"] is not None
    assert recipient_directory.list_all(settings.recipient_directory_path)


def test_resuming_a_thread_via_get_after_a_simulated_restart(tmp_path):
    """A fresh app/graph object (not the one that created the thread) must
    still be able to see and resolve the same pending approval, since the
    checkpointer is SQLite-backed rather than in-memory."""
    settings = _settings(tmp_path)
    _seed(settings, recipients=["A"])

    client1 = _client(settings)
    create = client1.post("/requests", json={"raw_request": "Pay 100 to A", "requester_id": "u1"}, headers=HEADERS)
    thread_id = create.json()["thread_id"]
    tx_id = create.json()["transactions"][0]["id"]
    del client1  # drop this app/client entirely — simulate the process exiting

    client2 = _client(settings)  # brand new FastAPI app + graph, same on-disk paths
    state = client2.get(f"/requests/{thread_id}", headers=HEADERS)
    assert state.status_code == 200
    assert state.json()["status"] == "pending_approval"
    assert state.json()["review_text"] == create.json()["review_text"]

    approve = client2.post(
        f"/requests/{thread_id}/approve",
        json={"selected_ids": [tx_id], "approver_id": "krish", "passphrase": "hunter2"},
        headers=HEADERS,
    )
    assert approve.status_code == 200
    assert approve.json()["results"][0]["status"] == "Completed"


def test_execution_failure_reflected_through_api(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, recipients=["A"])

    # build_graph isn't reachable through the API's own request cycle with a
    # custom execute_fn, so this test goes through the graph directly to
    # confirm the API's response models tolerate a Failed transaction, then
    # checks the same thread via the API.
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    from transaction_agent.graph import build_graph

    conn = sqlite3.connect(settings.checkpoint_db, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    graph = build_graph(
        checkpointer=saver,
        audit_path=settings.audit_path,
        recipient_directory_path=settings.recipient_directory_path,
        users_path=settings.users_path,
        execute_fn=lambda tx: {"success": False, "message": "insufficient funds"},
    )
    config = {"configurable": {"thread_id": "fixed-thread-1"}}
    from langgraph.types import Command

    out = graph.invoke(
        {
            "raw_input": "Pay 100 to A",
            "offline": True,
            "transactions": [],
            "audit_log": [],
            "processed_transactions": [],
        },
        config=config,
    )
    tx_id = out["__interrupt__"][0].value["transactions"][0]["id"]
    graph.invoke(
        Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "hunter2"}), config=config
    )
    conn.close()

    client = _client(settings)
    state = client.get("/requests/fixed-thread-1", headers=HEADERS)
    assert state.status_code == 200
    assert state.json()["status"] == "completed"
    assert state.json()["results"][0]["status"] == "Failed"
