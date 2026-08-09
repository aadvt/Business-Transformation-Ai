"""Google Sheets logging for negotiation outcomes — a supplementary view
for the owner, not the source of truth (transaction_agent/negotiations.py
and the Neon/SQLite table are authoritative). A Sheets failure never blocks
recording an outcome: append_negotiation_row() swallows errors and returns
whether it actually wrote, so callers can log/ignore rather than fail the
whole negotiation-outcome request over a spreadsheet hiccup.

Auth is a Google service account (machine credential, no interactive
OAuth) — set GOOGLE_SERVICE_ACCOUNT_JSON to the full JSON key content (not
a file path; this is what a Railway/etc. env var can hold directly) and
NEGOTIATION_SPREADSHEET_ID to the target spreadsheet. See
voice/setup_sheet.py to create and share a fresh sheet with these
credentials.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_HEADER = [
    "Timestamp",
    "Call SID",
    "Vendor",
    "Contact Person",
    "Outcome",
    "Agreed Amount",
    "Currency",
    "Purpose",
    "Notes",
    "Transaction ID",
]

# Columns of the "Vendor Directory" tab — filled in by the owner, referenced
# when placing an outbound call manually (contact/vendor/phone/purpose go
# into that call's user_data so the negotiation agent's {vendor_name} /
# {contact_person} / {purpose} template variables are populated).
VENDOR_DIRECTORY_HEADER = [
    "Contact Person",
    "Vendor Name",
    "Phone Number",
    "Category / What They're Called About",
    "Reference Amount",
    "Notes",
]

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]


def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        return None
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _worksheet():
    spreadsheet_id = os.environ.get("NEGOTIATION_SPREADSHEET_ID")
    if not spreadsheet_id:
        return None
    client = _client()
    if client is None:
        return None
    sheet = client.open_by_key(spreadsheet_id)
    try:
        ws = sheet.worksheet("Negotiations")
    except Exception:
        ws = sheet.add_worksheet(title="Negotiations", rows=1000, cols=len(_HEADER))
        ws.append_row(_HEADER)
    if ws.row_values(1) != _HEADER:
        ws.update(range_name="A1", values=[_HEADER])
    return ws


def append_negotiation_row(entry: dict[str, Any]) -> bool:
    """Returns True if the row was actually written, False if Sheets isn't
    configured or the write failed (never raises)."""
    try:
        ws = _worksheet()
        if ws is None:
            return False
        ws.append_row(
            [
                entry.get("created_at", ""),
                entry.get("call_sid", ""),
                entry.get("vendor_name", ""),
                entry.get("contact_person") or "",
                entry.get("outcome", ""),
                entry.get("agreed_amount") if entry.get("agreed_amount") is not None else "",
                entry.get("currency", ""),
                entry.get("purpose") or "",
                entry.get("notes") or "",
                entry.get("transaction_id") or "",
            ],
            value_input_option="USER_ENTERED",
        )
        return True
    except Exception as exc:  # never let a Sheets hiccup break outcome recording
        print(f"[voice.sheets] append_negotiation_row failed: {exc}", file=sys.stderr)
        return False


def get_vendor_directory() -> list[dict[str, Any]]:
    """Reads the "Vendor Directory" tab the owner fills in. Returns [] if
    Sheets isn't configured, the tab doesn't exist yet, or the read fails —
    this is a convenience lookup, never a hard dependency."""
    try:
        spreadsheet_id = os.environ.get("NEGOTIATION_SPREADSHEET_ID")
        if not spreadsheet_id:
            return []
        client = _client()
        if client is None:
            return []
        sheet = client.open_by_key(spreadsheet_id)
        ws = sheet.worksheet("Vendor Directory")
        return ws.get_all_records()
    except Exception as exc:
        print(f"[voice.sheets] get_vendor_directory failed: {exc}", file=sys.stderr)
        return []
