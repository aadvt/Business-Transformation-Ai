#!/usr/bin/env python3
"""One-time setup for the negotiation-outcomes Google Sheet.

Service accounts on a personal (non-Workspace) Google account have no
Drive storage quota of their own, so they can't *create* a new spreadsheet
file (Drive API returns "storage quota exceeded"). The standard
workaround, and the default mode here: you create a blank sheet in your
own Drive, share it with the service account as an Editor, and this script
just opens it and sets up the "Negotiations" tab + headers.

    export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat service-account-key.json)"
    python -m voice.setup_sheet --open-existing <spreadsheet_id_or_url>

If your service account *does* have Drive storage (e.g. a Workspace
domain with a Shared Drive), --create still works:

    python -m voice.setup_sheet --create --share-with you@example.com

Either way, prints the spreadsheet ID; set NEGOTIATION_SPREADSHEET_ID to
it (in .env locally, and as a Railway variable on voice-adapter) so
voice/sheets.py knows where to write.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from voice.sheets import _HEADER, _SCOPES


def _extract_id(id_or_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", id_or_url)
    return match.group(1) if match else id_or_url


def _client():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        print("GOOGLE_SERVICE_ACCOUNT_JSON is not set.", file=sys.stderr)
        return None

    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
    return gspread.authorize(creds)


def _init_worksheet(spreadsheet) -> None:
    ws = spreadsheet.sheet1
    if ws.title != "Negotiations":
        ws.update_title("Negotiations")
    if ws.row_values(1) != _HEADER:
        ws.update("A1", [_HEADER])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", default="Transaction Agent — Negotiation Outcomes")
    parser.add_argument(
        "--open-existing", metavar="ID_OR_URL", default=None, help="A sheet you created and shared with the service account"
    )
    parser.add_argument("--create", action="store_true", help="Have the service account create a new sheet (needs Drive quota)")
    parser.add_argument("--share-with", default=None, help="Google account email to share edit access with (only with --create)")
    args = parser.parse_args(argv)

    if not args.open_existing and not args.create:
        print("Pass either --open-existing <id_or_url> or --create.", file=sys.stderr)
        return 1

    client = _client()
    if client is None:
        return 1

    if args.open_existing:
        spreadsheet = client.open_by_key(_extract_id(args.open_existing))
    else:
        if not args.share_with:
            print("--create requires --share-with so you can actually see the sheet.", file=sys.stderr)
            return 1
        spreadsheet = client.create(args.title)
        spreadsheet.share(args.share_with, perm_type="user", role="writer")
        print(f"Shared with: {args.share_with}")

    _init_worksheet(spreadsheet)

    print(f"Spreadsheet ID: {spreadsheet.id}")
    print(f"URL: {spreadsheet.url}")
    print()
    print(f"Set NEGOTIATION_SPREADSHEET_ID={spreadsheet.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
