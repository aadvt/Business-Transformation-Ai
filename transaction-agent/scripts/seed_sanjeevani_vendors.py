#!/usr/bin/env python3
"""One-time seed: register Sanjeevani's fixture vendors as known recipients
so the settlement bridge (backend/app/transaction_agent_client.py) can
auto-resolve them to an exact match instead of falling into
recipient_disambiguation. Names must match
backend/app/mocks/fixtures/vendors.json exactly.

Stand-in until integration module 2 (point recipient resolution at
backend's live GET /vendors instead of a static list) is built.

Safe to re-run — skips names already present.

    python scripts/seed_sanjeevani_vendors.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transaction_agent import recipient_directory  # noqa: E402

VENDOR_NAMES = [
    "Shree Balaji Auto Components",
    "Kohinoor Precision Pvt Ltd",
    "Coromandel Tooling Works",
    "Marudhar Steel Traders",
    "Sundaram Logistics & Freight",
]


def main() -> None:
    existing = {row["name"] for row in recipient_directory.list_all()}
    for name in VENDOR_NAMES:
        if name in existing:
            print(f"skip (already present): {name}")
            continue
        recipient_id = recipient_directory.register(name=name, notes="Seeded from Sanjeevani vendor fixtures")
        print(f"registered: {name} -> {recipient_id}")


if __name__ == "__main__":
    main()
