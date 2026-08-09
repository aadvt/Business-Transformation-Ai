"""Outcomes of outbound vendor negotiation calls (a distinct concern from
the payment-approval flow in graph.py): who was called, whether they
accepted or declined, at what price, and any notes the agent captured.

Same dual-backend pattern as audit.py/recipient_directory.py/users.py: a
local file path uses SQLite (default — zero external dependencies, what
the test suite uses), a `postgres://`/`postgresql://` connection string
uses Postgres (Neon) instead, in the "transaction_agent" schema.
DEFAULT_NEGOTIATIONS_PATH picks Postgres automatically when DATABASE_URL
is set.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from typing import Any, Optional

from . import db
from .models import utcnow_iso

DEFAULT_NEGOTIATIONS_PATH = os.environ.get("DATABASE_URL") or os.environ.get(
    "NEGOTIATIONS_DB_PATH", "negotiations.sqlite"
)

_COLUMNS = (
    "entry_id",
    "call_sid",
    "vendor_name",
    "outcome",
    "agreed_amount",
    "currency",
    "purpose",
    "notes",
    "transcript_ref",
    "transaction_id",
    "created_at",
)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS negotiations (
    entry_id TEXT PRIMARY KEY,
    call_sid TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    agreed_amount REAL,
    currency TEXT NOT NULL DEFAULT 'INR',
    purpose TEXT,
    notes TEXT,
    transcript_ref TEXT,
    transaction_id TEXT,
    created_at TEXT NOT NULL
)
"""


# --- local SQLite backend ----------------------------------------------


def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _local_record(row: dict[str, Any], path: str) -> None:
    with closing(_sqlite_connect(path)) as conn:
        conn.execute(
            f"INSERT INTO negotiations ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})",
            [row[c] for c in _COLUMNS],
        )
        conn.commit()


def _local_list(path: str) -> list[dict[str, Any]]:
    with closing(_sqlite_connect(path)) as conn:
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM negotiations ORDER BY created_at").fetchall()
    return [dict(zip(_COLUMNS, r)) for r in rows]


# --- Postgres (Neon) backend ---------------------------------------------
#
# Schema-qualified rather than relying on search_path — see audit.py for
# why (Neon's pooled endpoint can hand consecutive statements to different
# backend sessions under PgBouncer transaction pooling).

_TABLE = f"{db.SCHEMA}.negotiations"

_PG_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    entry_id TEXT PRIMARY KEY,
    call_sid TEXT NOT NULL,
    vendor_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    agreed_amount DOUBLE PRECISION,
    currency TEXT NOT NULL DEFAULT 'INR',
    purpose TEXT,
    notes TEXT,
    transcript_ref TEXT,
    transaction_id TEXT,
    created_at TEXT NOT NULL
)
"""


def _pg_record(row: dict[str, Any], dsn: str) -> None:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        placeholders = ", ".join(["%s"] * len(_COLUMNS))
        conn.execute(
            f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [row[c] for c in _COLUMNS],
        )


def _pg_list(dsn: str) -> list[dict[str, Any]]:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        rows = conn.execute(f"SELECT {', '.join(_COLUMNS)} FROM {_TABLE} ORDER BY created_at").fetchall()
    return [dict(zip(_COLUMNS, r)) for r in rows]


# --- public API ---------------------------------------------------------


def record_outcome(
    call_sid: str,
    vendor_name: str,
    outcome: str,
    agreed_amount: Optional[float] = None,
    currency: str = "INR",
    purpose: Optional[str] = None,
    notes: Optional[str] = None,
    transcript_ref: Optional[str] = None,
    transaction_id: Optional[str] = None,
    path: str = DEFAULT_NEGOTIATIONS_PATH,
) -> str:
    if outcome not in ("accepted", "declined"):
        raise ValueError(f"outcome must be 'accepted' or 'declined', got {outcome!r}")
    entry_id = f"neg_{uuid.uuid4().hex[:12]}"
    row = {
        "entry_id": entry_id,
        "call_sid": call_sid,
        "vendor_name": vendor_name,
        "outcome": outcome,
        "agreed_amount": agreed_amount,
        "currency": currency,
        "purpose": purpose,
        "notes": notes,
        "transcript_ref": transcript_ref,
        "transaction_id": transaction_id,
        "created_at": utcnow_iso(),
    }
    if db.is_postgres_dsn(path):
        _pg_record(row, path)
    else:
        _local_record(row, path)
    return entry_id


def list_outcomes(path: str = DEFAULT_NEGOTIATIONS_PATH) -> list[dict[str, Any]]:
    if db.is_postgres_dsn(path):
        return _pg_list(path)
    return _local_list(path)
