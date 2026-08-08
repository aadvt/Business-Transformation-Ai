"""Simulated payment execution.

`simulate_execution` is the swappable seam: swap it out for a function that
calls a real payment provider (e.g. RTGS/NEFT/UPI rails) and nothing in
graph.py needs to change, because execute_node only ever calls whatever
`execute_fn` it was built with — see `build_graph(execute_fn=...)`.
"""

from __future__ import annotations

from typing import Any


def simulate_execution(transaction: dict[str, Any]) -> dict[str, Any]:
    """Pretend to execute a payment. No real payment rails are involved.

    Returns a dict with at least a "success" bool; on success/failure it
    should never raise for ordinary bad input — execute_node treats any
    exception raised here as a failure, so raising is reserved for truly
    unexpected errors you want surfaced as Failed transactions.
    """
    amount = transaction.get("amount", 0)
    recipient = transaction.get("recipient", "")

    if amount is None or amount <= 0:
        return {
            "success": False,
            "simulated": True,
            "message": f"Simulated rejection: non-positive amount ({amount!r})",
        }
    if not recipient or not str(recipient).strip():
        return {
            "success": False,
            "simulated": True,
            "message": "Simulated rejection: missing recipient",
        }

    return {
        "success": True,
        "simulated": True,
        "message": f"Simulated payment of {amount} {transaction.get('currency', 'INR')} to {recipient} completed.",
        "reference": f"SIM-{transaction.get('id', 'unknown')}",
    }
