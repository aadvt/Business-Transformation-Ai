#!/usr/bin/env python3
"""Terminal front end for the Transaction Agent graph.

All terminal I/O lives here — the graph itself (transaction_agent/graph.py)
never prints or reads from stdin, so it can be driven by a different front
end later (a service API, a voice agent, a watsonx Orchestrate import).

Usage:
    python cli.py "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
    python cli.py --offline "Pay 12,000 to ABC Logistics, 8,500 to Ravi Transport"
    python cli.py                      # prompts for the request interactively
"""

from __future__ import annotations

import argparse
import sys
import uuid

from dotenv import load_dotenv
from langgraph.types import Command

from transaction_agent.graph import build_graph
from transaction_agent.llm import WatsonxConfigError, check_env

load_dotenv()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transaction Agent — Phase 1 prototype")
    parser.add_argument("text", nargs="?", help="Natural-language payment request")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the built-in regex parser instead of watsonx.ai (no credentials needed)",
    )
    parser.add_argument("--audit-path", default=None, help="Path to the persistent audit log JSON file")
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


def run(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.offline:
        try:
            check_env()
        except WatsonxConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    text = args.text or input("Payment request: ").strip()
    if not text:
        print("No input given.", file=sys.stderr)
        return 1

    kwargs = {}
    if args.audit_path:
        kwargs["audit_path"] = args.audit_path
    graph = build_graph(**kwargs)

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = graph.invoke(
        {
            "raw_input": text,
            "offline": args.offline,
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

    payload = interrupts[0].value
    transactions = payload["transactions"]
    print()
    print(payload["review_text"])
    print()

    if not transactions:
        # Nothing was parsed; resume with an empty decision so the graph completes.
        graph.invoke(Command(resume={"selected_ids": [], "approved_by": "n/a"}), config=config)
        print("Nothing to approve.")
        return 0

    while True:
        indices = prompt_selection(len(transactions))
        selected = [transactions[i - 1] for i in indices]
        total = sum(tx["amount"] for tx in selected)
        currency = selected[0]["currency"] if selected else "INR"
        if not selected:
            print("No transactions selected.")
        else:
            print(f"Selected {len(selected)} of {len(transactions)}: total {total:,.2f} {currency}")
        confirm = input("Confirm this selection? [y/N]: ").strip().lower()
        if confirm in ("y", "yes"):
            break
        print("Let's try again.")

    approved_by = input("Approver name: ").strip() or "unknown"
    selected_ids = [transactions[i - 1]["id"] for i in indices]

    final_state = graph.invoke(
        Command(resume={"selected_ids": selected_ids, "approved_by": approved_by}),
        config=config,
    )

    print()
    print("Results:")
    for tx in final_state.get("processed_transactions", []):
        result_note = ""
        if tx.get("execution_result"):
            result_note = f" — {tx['execution_result'].get('message') or tx['execution_result'].get('error')}"
        print(f"  {tx['recipient']}: {tx['amount']:,.2f} {tx['currency']} -> {tx['status']}{result_note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
