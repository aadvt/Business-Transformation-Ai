"""Persistent audit log: append-only store of every state transition.

Writes are idempotent (deduped by entry_id) because log_node runs once per
transaction inside a LangGraph map-reduce fan-out, and interrupt() replay
means a node's audit-producing code could in principle run more than once.

Two backends behind the same three functions, selected by what `path` looks
like: a local file path uses JSON (default — zero external dependencies,
what the test suite uses), a `postgres://`/`postgresql://` connection
string uses Postgres (Neon) instead, in the "transaction_agent" schema.
DEFAULT_AUDIT_LOG_PATH picks Postgres automatically when DATABASE_URL is
set, so production usage gets it for free without every call site changing.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from . import db

DEFAULT_AUDIT_LOG_PATH = os.environ.get("DATABASE_URL") or os.environ.get("AUDIT_LOG_PATH", "audit_log.json")

_lock = threading.Lock()


# --- local JSON file backend ------------------------------------------------


def _local_read(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _local_write(path: str, entries: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)
    tmp.replace(p)


def _local_append_entries(entries: list[dict[str, Any]], path: str) -> list[dict[str, Any]]:
    with _lock:
        existing = _local_read(path)
        existing_ids = {e.get("entry_id") for e in existing}
        fresh = [e for e in entries if e.get("entry_id") not in existing_ids]
        if fresh:
            existing.extend(fresh)
            _local_write(path, existing)
        return fresh


def _local_read_all(path: str) -> list[dict[str, Any]]:
    with _lock:
        return _local_read(path)


def _local_clear(path: str) -> None:
    with _lock:
        if Path(path).exists():
            Path(path).unlink()


# --- Postgres (Neon) backend -------------------------------------------------
#
# Every statement schema-qualifies the table (transaction_agent.audit_entries)
# rather than relying on the connection's `search_path` — DATABASE_URL is
# Neon's pooled (PgBouncer) endpoint, which can transparently hand
# consecutive statements to different backend sessions, silently dropping
# session-level state like `SET search_path`. Schema-qualifying makes every
# statement self-contained regardless of which backend session runs it.

_ENTRY_COLUMNS = ("entry_id", "transaction_id", "from_status", "to_status", "timestamp", "note", "channel", "call_id", "transcript_ref")
_TABLE = f"{db.SCHEMA}.audit_entries"

_PG_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id SERIAL PRIMARY KEY,
    entry_id TEXT UNIQUE NOT NULL,
    transaction_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    note TEXT,
    channel TEXT,
    call_id TEXT,
    transcript_ref TEXT
)
"""


def _pg_append_entries(entries: list[dict[str, Any]], dsn: str) -> list[dict[str, Any]]:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        fresh = []
        for e in entries:
            row = conn.execute(
                f"""
                INSERT INTO {_TABLE} (entry_id, transaction_id, from_status, to_status, timestamp, note, channel, call_id, transcript_ref)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (entry_id) DO NOTHING
                RETURNING entry_id
                """,
                [e.get(c) for c in _ENTRY_COLUMNS],
            ).fetchone()
            if row is not None:
                fresh.append(e)
        return fresh


def _pg_read_all(dsn: str) -> list[dict[str, Any]]:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        cur = conn.execute(f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM {_TABLE} ORDER BY id")
        return [dict(zip(_ENTRY_COLUMNS, row)) for row in cur.fetchall()]


def _pg_clear(dsn: str) -> None:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        conn.execute(f"DELETE FROM {_TABLE}")


# --- public API ---------------------------------------------------------


def append_entries(entries: list[dict[str, Any]], path: str = DEFAULT_AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    """Append entries to the persistent log, skipping any entry_id already present.

    Returns the subset of entries that were actually newly written.
    """
    if not entries:
        return []
    if db.is_postgres_dsn(path):
        return _pg_append_entries(entries, path)
    return _local_append_entries(entries, path)


def read_all(path: str = DEFAULT_AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    if db.is_postgres_dsn(path):
        return _pg_read_all(path)
    return _local_read_all(path)


def clear(path: str = DEFAULT_AUDIT_LOG_PATH) -> None:
    if db.is_postgres_dsn(path):
        _pg_clear(path)
        return
    _local_clear(path)
