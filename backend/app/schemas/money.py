"""Money and timestamp helpers.

All money in Sanjeevani is an integer number of paise (1 rupee = 100 paise),
carried in fields suffixed `_paise`. Never use float for money.
"""

from datetime import datetime, timezone


def format_inr(paise: int) -> str:
    """Format paise as a full Indian-grouped rupee string, e.g. 6200000 -> "₹62,00,000"."""
    rupees = paise // 100
    sign = "-" if rupees < 0 else ""
    rupees = abs(rupees)
    s = str(rupees)
    if len(s) <= 3:
        grouped = s
    else:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        grouped = ",".join(parts) + "," + last3
    return f"{sign}₹{grouped}"


def format_inr_short(paise: int) -> str:
    """Format paise as a short Indian magnitude string, e.g. 6200000000 -> "₹62.0Cr"."""
    rupees = paise / 100
    sign = "-" if rupees < 0 else ""
    rupees = abs(rupees)
    if rupees >= 1_00_00_000:
        return f"{sign}₹{rupees / 1_00_00_000:.1f}Cr"
    if rupees >= 1_00_000:
        return f"{sign}₹{rupees / 1_00_000:.1f}L"
    if rupees >= 1_000:
        return f"{sign}₹{rupees / 1_000:.1f}K"
    return f"{sign}₹{rupees:.0f}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()
