"""Small regex-based parser used by --offline mode, so the whole flow is demoable
with zero credentials. Not a substitute for the LLM parser's language coverage.

Deliberately does not split the input on commas first: comma is also the
thousands separator ("12,000"), so segmentation is driven by the pattern
match itself instead.
"""

from __future__ import annotations

import re

from .models import ParsedTransactionItem, ParsedTransactionList

_AMOUNT = r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CURRENCY = r"(?:rs\.?|inr|₹)"

_INSTRUCTION = re.compile(
    rf"{_CURRENCY}?\s*{_AMOUNT}\s*{_CURRENCY}?\s+to\s+"
    rf"(?P<recipient>[A-Za-z][\w&.'\-]*(?:\s+[A-Za-z][\w&.'\-]*)*?)"
    rf"(?:\s+for\s+(?P<purpose>[\w &.'\-]+?))?"
    rf"(?=\s*(?:,|;|\band\b|$))",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_offline(text: str) -> ParsedTransactionList:
    """Find every "<amount> to <recipient>[ for <purpose>]" instruction in the text."""
    items: list[ParsedTransactionItem] = []
    for match in _INSTRUCTION.finditer(text):
        groups = match.groupdict()
        recipient = groups["recipient"].strip().strip(".")
        if not recipient:
            continue
        purpose = groups.get("purpose")
        purpose = purpose.strip() if purpose else None
        items.append(
            ParsedTransactionItem(
                recipient=recipient,
                amount=_to_float(groups["amount"]),
                currency="INR",
                purpose=purpose,
            )
        )
    return ParsedTransactionList(transactions=items)
