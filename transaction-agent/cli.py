#!/usr/bin/env python3
"""Terminal front end for the Transaction Agent graph.

All terminal I/O lives here — the graph itself (transaction_agent/graph.py)
never prints or reads from stdin, so it can be driven by a different front
end later (a service API, a voice agent, a watsonx Orchestrate import).

Usage:
    python cli.py "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
    python cli.py --offline "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
    python cli.py                      # prompts for the request interactively
    python cli.py --resume <thread_id> # continue a paused approval, even
                                        # after this process previously exited
    python cli.py --resume             # continue the most recently started thread

Checkpoints are persisted to SQLite (--checkpoint-db, default
checkpoints.sqlite), so a pending approval survives the process restarting.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from transaction_agent.graph import build_graph
from transaction_agent.llm import WatsonxConfigError, check_env

load_dotenv()

LAST_THREAD_FILE = ".transaction_agent_last_thread"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transaction Agent — prototype")
    parser.add_argument("text", nargs="?", help="Natural-language payment request")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the built-in regex parser instead of watsonx.ai (no credentials needed)",
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="__last__",
        default=None,
        metavar="THREAD_ID",
        help="Continue a paused approval. Omit the id to resume the most recently started thread.",
    )
    parser.add_argument("--audit-path", default=None, help="Path to the persistent audit log JSON file")
    parser.add_argument("--checkpoint-db", default="checkpoints.sqlite", help="SQLite file for graph checkpoints")
    parser.add_argument("--recipient-directory", default=None, help="SQLite file for the recipient directory")
    parser.add_argument("--users-db", default=None, help="SQLite file for the local approver user table")
    return parser.parse_args(argv)


def prompt_selection(num_transactions: int) -> list[int]:
    """Checkbox-style selection: comma-separated 1-based indices, 'all', or 'none'."""
    while True:
        raw = input(
            f"Select transactions to approve [1-{num_transactions}, comma-separated, "
            "'all', or 'none']: "
        ).strip().lower()
        if raw in ("all", "a"):
            return list(range(1, num_transactions + 1))
        if raw in ("none", "n", ""):
            return []
        try:
            indices = sorted({int(part.strip()) for part in raw.split(",") if part.strip()})
        except ValueError:
            print("Could not parse that. Use numbers like '1,3', 'all', or 'none'.")
            continue
        if any(i < 1 or i > num_transactions for i in indices):
            print(f"Numbers must be between 1 and {num_transactions}.")
            continue
        return indices


def handle_recipient_disambiguation(payload: dict) -> dict:
    print()
    print("Some recipients need a human decision before review:")
    choices: dict[str, dict] = {}
    for item in payload["pending"]:
        print(f"\n  '{item['recipient_text']}' ({item['amount']:,.2f}) — {item['status']} match")
        candidates = item["candidates"]
        for idx, c in enumerate(candidates, start=1):
            print(f"    [{idx}] {c['name']}  (score {c['score']:.2f}, {c['recipient_id']})")
        print(f"    [n] Register '{item['recipient_text']}' as a new recipient")
        print("    [enter] Leave unresolved for now")

        raw = input("  Choice: ").strip().lower()
        if raw == "n":
            notes = input("  Notes for new recipient (optional): ").strip() or None
            choices[item["transaction_id"]] = {"register_new": {"name": item["recipient_text"], "notes": notes}}
        elif raw.isdigit() and 1 <= int(raw) <= len(candidates):
            choices[item["transaction_id"]] = {"recipient_id": candidates[int(raw) - 1]["recipient_id"]}
        # anything else (blank, garbage): leave unresolved

    return {"choices": choices}


def handle_transaction_approval(payload: dict, remembered: dict) -> dict:
    if payload.get("error"):
        print(f"\n{payload['error']}")
    else:
        transactions = payload["transactions"]
        print()
        print(payload["review_text"])
        print()
        indices = prompt_selection(len(transactions))
        selected = [transactions[i - 1] for i in indices]
        total = sum(tx["amount"] for tx in selected)
        currency = selected[0]["currency"] if selected else "INR"
        if selected:
            print(f"Selected {len(selected)} of {len(transactions)}: total {total:,.2f} {currency}")
        else:
            print("No transactions selected.")
        remembered["selected_ids"] = [transactions[i - 1]["id"] for i in indices]

    username = input("Approver username: ").strip()
    passphrase = getpass.getpass("Passphrase: ")
    return {"username": username, "passphrase": passphrase, "selected_ids": remembered.get("selected_ids") or []}


def drive_interrupts(graph, config, interrupts) -> dict:
    """Repeatedly render whatever interrupt is pending and resume until the
    graph completes, returning the final state."""
    remembered: dict = {}
    state = None
    while interrupts:
        payload = interrupts[0].value
        kind = payload["kind"]
        if kind == "recipient_disambiguation":
            resume_value = handle_recipient_disambiguation(payload)
        elif kind == "transaction_approval":
            resume_value = handle_transaction_approval(payload, remembered)
        else:
            raise RuntimeError(f"Unknown interrupt kind: {kind!r}")

        state = graph.invoke(Command(resume=resume_value), config=config)
        interrupts = state.get("__interrupt__")
    return state or {}


def run(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.offline:
        try:
            check_env()
        except WatsonxConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    conn = sqlite3.connect(args.checkpoint_db, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()

    build_kwargs = {"checkpointer": saver}
    if args.audit_path:
        build_kwargs["audit_path"] = args.audit_path
    if args.recipient_directory:
        build_kwargs["recipient_directory_path"] = args.recipient_directory
    if args.users_db:
        build_kwargs["users_path"] = args.users_db
    graph = build_graph(**build_kwargs)

    try:
        if args.resume:
            thread_id = args.resume
            if thread_id == "__last__":
                if not Path(LAST_THREAD_FILE).exists():
                    print(f"No prior thread recorded in {LAST_THREAD_FILE}.", file=sys.stderr)
                    return 1
                thread_id = Path(LAST_THREAD_FILE).read_text().strip()
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = graph.get_state(config)
            interrupts = [i for task in snapshot.tasks for i in task.interrupts]
            if not interrupts:
                print(f"Nothing pending for thread {thread_id!r} (already completed, or unknown thread).")
                return 0
            print(f"Resuming thread {thread_id}...")
        else:
            text = args.text or input("Payment request: ").strip()
            if not text:
                print("No input given.", file=sys.stderr)
                return 1

            thread_id = str(uuid.uuid4())
            Path(LAST_THREAD_FILE).write_text(thread_id)
            print(f"Thread id: {thread_id}  (resume later with --resume {thread_id})")

            config = {"configurable": {"thread_id": thread_id}}
            state = graph.invoke(
                {
                    "raw_input": text,
                    "offline": args.offline,
                    "channel": "cli",
                    "transactions": [],
                    "audit_log": [],
                    "processed_transactions": [],
                },
                config=config,
            )
            interrupts = state.get("__interrupt__")
            if not interrupts:
                print("No approval was required (nothing parsed).")
                return 0

        final_state = drive_interrupts(graph, config, interrupts)

        print()
        print("Results:")
        for tx in final_state.get("processed_transactions", []):
            result_note = ""
            if tx.get("execution_result"):
                result_note = f" — {tx['execution_result'].get('message') or tx['execution_result'].get('error')}"
            recipient_id = f" [{tx['recipient_id']}]" if tx.get("recipient_id") else ""
            print(f"  {tx['recipient']}{recipient_id}: {tx['amount']:,.2f} {tx['currency']} -> {tx['status']}{result_note}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
