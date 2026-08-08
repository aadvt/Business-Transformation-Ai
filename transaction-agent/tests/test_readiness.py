"""Readiness checks for importing this graph elsewhere (a service, or
watsonx Orchestrate's "import LangGraph agents" feature): no hidden
stdin/stdout dependency, and build_graph() produces fully independent
instances with no shared mutable state. See the README's "Orchestrate
readiness" section for the full write-up — these tests are what that
write-up is based on, not just a claim.
"""

import ast
import pathlib
import uuid

from langgraph.types import Command

from transaction_agent import recipient_directory, users
from transaction_agent.graph import build_graph

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent / "transaction_agent"

# Modules a graph-import mechanism would actually load and execute. users.py
# is checked separately below: its print()/input() usage is confined to a
# `python -m transaction_agent.users` CLI helper, never touched on import.
CORE_MODULES = [
    "graph.py",
    "models.py",
    "state_machine.py",
    "execution.py",
    "parsing_offline.py",
    "audit.py",
    "recipient_directory.py",
    "llm.py",
]


def _stdio_calls(source: str) -> list[tuple[str | None, int]]:
    tree = ast.parse(source)
    calls: list[tuple[str | None, int]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            if isinstance(node.func, ast.Name) and node.func.id in ("print", "input"):
                calls.append((self.stack[-1] if self.stack else None, node.lineno))
            self.generic_visit(node)

    Visitor().visit(tree)
    return calls


def test_core_modules_have_no_stdin_stdout_dependency():
    for filename in CORE_MODULES:
        source = (PACKAGE_DIR / filename).read_text()
        calls = _stdio_calls(source)
        assert calls == [], f"{filename} calls print()/input() at lines {calls}"


def test_users_module_confines_stdio_to_its_cli_helper():
    source = (PACKAGE_DIR / "users.py").read_text()
    calls = _stdio_calls(source)
    assert calls, "expected the known _main() print() — update this test if users.py changed"
    assert all(fn == "_main" for fn, _ in calls), f"stdio call outside _main(): {calls}"


def _paths(tmp_path, tag):
    d = tmp_path / tag
    d.mkdir()
    return {
        "audit_path": str(d / "audit.json"),
        "recipient_directory_path": str(d / "recipients.sqlite"),
        "users_path": str(d / "users.sqlite"),
    }


def _initial_state(text):
    return {
        "raw_input": text,
        "offline": True,
        "transactions": [],
        "audit_log": [],
        "processed_transactions": [],
    }


def test_independently_built_graphs_share_no_state(tmp_path):
    """Two build_graph() calls, two entirely separate on-disk stores, two
    thread ids, invoked interleaved. Nothing from one should be visible
    through the other — the property an import-per-request (or
    import-per-tenant) deployment relies on."""
    paths_a = _paths(tmp_path, "a")
    paths_b = _paths(tmp_path, "b")
    users.create_user("alice", "alicepass", path=paths_a["users_path"])
    users.create_user("bob", "bobpass", path=paths_b["users_path"])
    recipient_directory.register("Alpha Corp", path=paths_a["recipient_directory_path"])
    recipient_directory.register("Beta LLC", path=paths_b["recipient_directory_path"])

    graph_a = build_graph(**paths_a)
    graph_b = build_graph(**paths_b)

    config_a = {"configurable": {"thread_id": str(uuid.uuid4())}}
    config_b = {"configurable": {"thread_id": str(uuid.uuid4())}}

    # interleaved: start B before finishing A
    out_a = graph_a.invoke(_initial_state("Pay 100 to Alpha Corp"), config=config_a)
    out_b = graph_b.invoke(_initial_state("Pay 200 to Beta LLC"), config=config_b)

    tx_a = out_a["__interrupt__"][0].value["transactions"][0]
    tx_b = out_b["__interrupt__"][0].value["transactions"][0]
    assert tx_a["recipient"] == "Alpha Corp"
    assert tx_b["recipient"] == "Beta LLC"

    # resume B, then A — order matters, proving no shared/global cursor
    final_b = graph_b.invoke(
        Command(resume={"selected_ids": [tx_b["id"]], "username": "bob", "passphrase": "bobpass"}), config=config_b
    )
    final_a = graph_a.invoke(
        Command(resume={"selected_ids": [tx_a["id"]], "username": "alice", "passphrase": "alicepass"}),
        config=config_a,
    )

    assert final_a["processed_transactions"][0]["recipient"] == "Alpha Corp"
    assert final_b["processed_transactions"][0]["recipient"] == "Beta LLC"

    # bob's credentials must not work against a's user store, and vice versa
    assert not users.verify("bob", "bobpass", path=paths_a["users_path"])
    assert not users.verify("alice", "alicepass", path=paths_b["users_path"])

    # each recipient directory only knows about its own vendor
    a_names = {r["name"] for r in recipient_directory.list_all(paths_a["recipient_directory_path"])}
    b_names = {r["name"] for r in recipient_directory.list_all(paths_b["recipient_directory_path"])}
    assert "Beta LLC" not in a_names
    assert "Alpha Corp" not in b_names


def test_build_graph_called_fresh_per_call_against_same_store_is_safe(tmp_path):
    """Simulates exactly what api.py's get_graph() dependency does per
    request: a brand new build_graph() call (and, like the API, a brand
    new SqliteSaver connection) every time, all pointed at the same
    on-disk checkpoint file, operating on different threads without
    interference — including a resume happening through a *different*
    build_graph() call than the one that started the thread."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    paths = _paths(tmp_path, "shared")
    checkpoint_db = str(tmp_path / "shared" / "checkpoints.sqlite")
    users.create_user("krish", "hunter2", path=paths["users_path"])
    recipient_directory.register("Shared Vendor", path=paths["recipient_directory_path"])

    def fresh_graph():
        conn = sqlite3.connect(checkpoint_db, check_same_thread=False)
        saver = SqliteSaver(conn)
        saver.setup()
        return conn, build_graph(checkpointer=saver, **paths)

    thread_ids = [str(uuid.uuid4()) for _ in range(3)]
    tx_ids = {}
    for tid in thread_ids:
        conn, graph = fresh_graph()  # a fresh instance per "request", like get_graph()
        config = {"configurable": {"thread_id": tid}}
        out = graph.invoke(_initial_state("Pay 50 to Shared Vendor"), config=config)
        tx_ids[tid] = out["__interrupt__"][0].value["transactions"][0]["id"]
        conn.close()

    for tid, tx_id in tx_ids.items():
        conn, graph = fresh_graph()  # a *different* fresh instance resumes each thread
        config = {"configurable": {"thread_id": tid}}
        final = graph.invoke(
            Command(resume={"selected_ids": [tx_id], "username": "krish", "passphrase": "hunter2"}), config=config
        )
        conn.close()
        assert final["processed_transactions"][0]["status"] == "Completed"
