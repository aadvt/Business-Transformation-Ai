"""Shared Postgres connection helper for the Neon-backed persistence path.

Every store module (audit.py, recipient_directory.py, users.py) keeps
accepting the same `path` parameter it always has: a local file path
selects the SQLite/JSON backend (zero external dependencies — what tests
and offline/local dev use), while a `postgres://` or `postgresql://`
connection string selects this Postgres backend instead. Nothing calling
into those modules (graph.py, api.py, cli.py, voice/adapter.py) needs to
know or care which backend is active.

All transaction_agent tables live in the "transaction_agent" Postgres
schema (created on first use), kept separate from any other service
sharing the same database — e.g. this project's own backend/, whose
tables live in "public".
"""

from __future__ import annotations

import time

import psycopg
from psycopg.rows import dict_row

SCHEMA = "transaction_agent"

_CONNECT_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 1.5


def is_postgres_dsn(path: str) -> bool:
    return path.startswith("postgres://") or path.startswith("postgresql://")


def _connect_with_retry(dsn: str, *, set_search_path: bool, **kwargs) -> psycopg.Connection:
    """A few retries: a serverless Neon compute waking from auto-suspend can
    transiently fail (or briefly not see just-created objects) on the very
    first connection or two."""
    last_error: Exception | None = None
    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            conn = psycopg.connect(dsn, connect_timeout=10, **kwargs)
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            if set_search_path:
                conn.execute(f"SET search_path TO {SCHEMA}, public")
            return conn
        except psycopg.Error as exc:
            last_error = exc
            if attempt < _CONNECT_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS)
    raise last_error


def connect(dsn: str) -> psycopg.Connection:
    """For audit.py/recipient_directory.py/users.py: short-lived connections
    against Neon's pooled endpoint. No reliance on `search_path` — PgBouncer
    transaction pooling can hand consecutive statements to different backend
    sessions, silently dropping session-level state, so every caller
    schema-qualifies its own table names instead (see e.g. audit.py's _TABLE)."""
    return _connect_with_retry(dsn, set_search_path=False, autocommit=True)


def connect_for_checkpointer(dsn: str) -> psycopg.Connection:
    """For langgraph's PostgresSaver: mirrors PostgresSaver.from_conn_string's
    own connection kwargs (autocommit, no server-side prepared statements —
    the standard PgBouncer-safety flag, in case this DSN is pooled — and
    dict-shaped rows, which PostgresSaver's internals expect). search_path IS
    set here because PostgresSaver's own internal SQL isn't schema-qualified
    and we can't change it — safe because this uses DATABASE_URL_DIRECT, a
    single long-lived session with no pooler multiplexing to worry about."""
    return _connect_with_retry(dsn, set_search_path=True, autocommit=True, prepare_threshold=0, row_factory=dict_row)
