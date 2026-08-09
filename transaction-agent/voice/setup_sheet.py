#!/usr/bin/env python3
"""One-time setup: create the negotiation-outcomes Google Sheet and share
it with the owner's Google account (a service account's files are private
to itself by default — without this share, the owner could never see it).

    export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service-account-key.json)"
    python -m voice.setup_sheet --share-with you@example.com

Prints the spreadsheet ID and URL; set NEGOTIATION_SPREADSHEET_ID to that
ID (in .env locally, and as a Railway variable on voice-adapter) so
voice/sheets.py knows where to write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from voice.sheets import _HEADER, _SCOPES


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", default="Transaction Agent — Negotiation Outcomes")
    parser.add_argument("--share-with", required=True, help="Google account email to share edit access with")
    args = parser.parse_args(argv)

    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        print("GOOGLE_SERVICE_ACCOUNT_JSON is not set.", file=sys.stderr)
        return 1

    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    client = gspread.authorize(creds)

    spreadsheet = client.create(args.title)
    spreadsheet.share(args.share_with, perm_type="user", role="writer")

    ws = spreadsheet.sheet1
    ws.update_title("Negotiations")
    ws.append_row(_HEADER)

    print(f"Spreadsheet ID: {spreadsheet.id}")
    print(f"URL: {spreadsheet.url}")
    print(f"Shared with: {args.share_with}")
    print()
    print(f"Set NEGOTIATION_SPREADSHEET_ID={spreadsheet.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
