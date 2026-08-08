"""Small, dependency-free helpers for turning spoken/DTMF input into the
same selection indices the CLI's prompt_selection() produces, and for
turning review data into natural-language text for TTS to read.

None of this makes business decisions — it only maps text <-> structured
data that voice/adapter.py then hands to api.py exactly like the CLI or a
direct API caller would.

DTMF note: Bolna's docs confirm DTMF capture exists (the dashboard's Call
Tab has a DTMF option) but don't publish an exact webhook payload shape.
Rather than guess one, parse_dtmf_selection() defines our own convention —
digits separated by '*', optionally terminated by '#', with '0' for "none"
and '9' for "all" — and voice/adapter.py's tool schema documents this
convention for whoever wires up the DTMF side in the Bolna dashboard.
"""

from __future__ import annotations

import re

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

_ORDINAL_WORDS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

_ALL_WORDS = {"all", "everything", "all of them", "both", "every one", "all of it"}
_NONE_WORDS = {"none", "nothing", "no", "neither", "cancel", "skip"}

_AFFIRMATIVE_WORDS = {"confirm", "confirmed", "yes", "yeah", "yep", "correct", "go ahead", "do it", "proceed", "1", "#"}
_NEGATIVE_WORDS = {"cancel", "no", "nope", "stop", "wait", "back", "redo", "2", "0"}


def _extract_numbers(text: str) -> list[int]:
    found: list[int] = []
    # digits, e.g. "1, 3" or "1 and 3"
    for match in re.finditer(r"\d+", text):
        found.append(int(match.group()))
    # word numbers / ordinals
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in _WORD_NUMBERS:
            found.append(_WORD_NUMBERS[word])
        elif word in _ORDINAL_WORDS:
            found.append(_ORDINAL_WORDS[word])
    # de-dupe, keep order of first appearance
    seen: list[int] = []
    for n in found:
        if n not in seen:
            seen.append(n)
    return seen


def parse_selection(text: str, num_transactions: int) -> list[int]:
    """"one and three" / "1,3" / "all" / "none" -> sorted 1-based indices,
    clamped to [1, num_transactions]. Unparseable or out-of-range numbers
    are silently dropped rather than raising — the caller (adapter) reads
    the returned selection back for confirmation, so a caller who misheard
    something gets a chance to catch it there instead of a hard error."""
    normalized = text.strip().lower()
    if normalized in _ALL_WORDS or "all" in normalized.split():
        return list(range(1, num_transactions + 1))
    if normalized in _NONE_WORDS:
        return []
    numbers = [n for n in _extract_numbers(normalized) if 1 <= n <= num_transactions]
    return sorted(set(numbers))


def parse_dtmf_selection(digits: str, num_transactions: int) -> list[int]:
    """See module docstring for the '*'-separated / '#'-terminated / 0=none /
    9=all convention this implements."""
    digits = digits.strip().rstrip("#")
    if digits == "0":
        return []
    if digits == "9":
        return list(range(1, num_transactions + 1))
    numbers = []
    for part in digits.split("*"):
        if part.isdigit():
            n = int(part)
            if 1 <= n <= num_transactions:
                numbers.append(n)
    return sorted(set(numbers))


def _matches_any_word(text: str, words: set[str]) -> bool:
    normalized = text.strip().lower()
    if normalized in words:
        return True
    tokens = set(re.findall(r"[a-z]+|\d+|#", normalized))
    return bool(tokens & words)


def is_affirmative(text: str) -> bool:
    return _matches_any_word(text, _AFFIRMATIVE_WORDS) or "go ahead" in text.lower() or "yes please" in text.lower()


def is_negative(text: str) -> bool:
    return _matches_any_word(text, _NEGATIVE_WORDS)


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = [
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _under_thousand_to_words(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} hundred")
        n %= 100
        if n:
            parts.append("and")
    if 10 <= n < 20:
        parts.append(_TEENS[n - 10])
    else:
        if n >= 20:
            parts.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
        elif n > 0:
            parts.append(_ONES[n])
    return " ".join(p for p in parts if p)


def number_to_words(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + number_to_words(-n)

    groups = [("crore", 10_000_000), ("lakh", 100_000), ("thousand", 1_000)]
    words = []
    remainder = n
    for name, size in groups:
        if remainder >= size:
            count = remainder // size
            words.append(f"{_under_thousand_to_words(count)} {name}")
            remainder %= size
    if remainder or not words:
        words.append(_under_thousand_to_words(remainder))
    return " ".join(w for w in words if w).strip()


_CURRENCY_WORDS = {"INR": "rupees"}


def amount_to_words(amount: float, currency: str = "INR") -> str:
    whole = int(amount)
    currency_word = _CURRENCY_WORDS.get(currency, currency)
    text = f"{number_to_words(whole)} {currency_word}"
    cents = round((amount - whole) * 100)
    if cents:
        text += f" and {number_to_words(cents)} paise"
    return text


def format_review_for_voice(transactions: list[dict]) -> str:
    if not transactions:
        return "I didn't catch any payments to make from that. Could you say the payment again?"

    ordinal_names = list(_ORDINAL_WORDS.keys())
    lines = [f"I found {len(transactions)} payment{'s' if len(transactions) != 1 else ''} to review."]
    total = 0.0
    for idx, tx in enumerate(transactions):
        position = ordinal_names[idx].capitalize() if idx < len(ordinal_names) else f"Number {idx + 1}"
        purpose = f", for {tx['purpose']}" if tx.get("purpose") else ""
        lines.append(f"{position}: {amount_to_words(tx['amount'], tx['currency'])} to {tx['recipient']}{purpose}.")
        total += tx["amount"]
    currency = transactions[0]["currency"]
    lines.append(
        f"That's a total of {amount_to_words(total, currency)} across "
        f"{len(transactions)} payment{'s' if len(transactions) != 1 else ''}. "
        "Which would you like to approve — you can say 'all', 'none', or list them, like 'one and three'?"
    )
    return " ".join(lines)


def format_selection_confirmation(selected: list[dict], total: float, currency: str) -> str:
    if not selected:
        return "You didn't select any payments, so nothing will be approved. Say 'confirm' to proceed with no payments, or list the ones you'd like to approve."
    names = ", ".join(f"{tx['recipient']} for {amount_to_words(tx['amount'], tx['currency'])}" for tx in selected)
    return (
        f"You selected {len(selected)} payment{'s' if len(selected) != 1 else ''}: {names}. "
        f"That's a total of {amount_to_words(total, currency)}. "
        f"Say 'confirm' to pay {amount_to_words(total, currency)}, or 'cancel' to change your selection."
    )
