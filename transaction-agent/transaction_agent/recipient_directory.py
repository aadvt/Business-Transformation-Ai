"""Recipient directory: known payees, fuzzy-matched against parsed
transaction recipients so recipient_id can be filled in automatically for a
clean match, or routed to a human for disambiguation otherwise.

Not a production identity system — no dedup merging, no admin UI. Just
enough to make recipient_id something other than always-null.

Two backends behind the same functions, selected by what `path` looks
like: a local file path uses SQLite (default — zero external dependencies,
what the test suite uses), a `postgres://`/`postgresql://` connection
string uses Postgres (Neon) instead, in the "transaction_agent" schema.
DEFAULT_DIRECTORY_PATH picks Postgres automatically when DATABASE_URL is
set, so production usage gets it for free without every call site changing.
"""

from __future__ import annotations

import difflib
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from typing import Optional

from . import db

DEFAULT_DIRECTORY_PATH = os.environ.get("DATABASE_URL") or os.environ.get(
    "RECIPIENT_DIRECTORY_PATH", "recipient_directory.sqlite"
)

EXACT_SCORE = 0.90
CANDIDATE_SCORE = 0.55
CLOSE_GAP = 0.08

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS recipients (
    recipient_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    notes TEXT
)
"""


@dataclass
class Candidate:
    recipient_id: str
    name: str
    score: float


@dataclass
class Resolution:
    status: str  # "auto" | "ambiguous" | "none"
    candidates: list[Candidate] = field(default_factory=list)
    recipient_id: Optional[str] = None


# --- local SQLite backend ----------------------------------------------


def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_CREATE_TABLE)  # the same DDL is valid SQLite too
    conn.commit()
    return conn


def _local_register(name: str, notes: Optional[str], aliases: list[str], path: str) -> str:
    recipient_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    with closing(_sqlite_connect(path)) as conn:
        conn.execute(
            "INSERT INTO recipients (recipient_id, name, aliases, notes) VALUES (?, ?, ?, ?)",
            (recipient_id, name, ",".join(aliases), notes),
        )
        conn.commit()
    return recipient_id


def _local_list_all(path: str) -> list[dict]:
    with closing(_sqlite_connect(path)) as conn:
        rows = conn.execute("SELECT recipient_id, name, aliases, notes FROM recipients").fetchall()
    return [{"recipient_id": r[0], "name": r[1], "aliases": r[2], "notes": r[3]} for r in rows]


# --- Postgres (Neon) backend ---------------------------------------------
#
# Schema-qualified (transaction_agent.recipients) rather than relying on
# search_path — DATABASE_URL is Neon's pooled endpoint, which can hand
# consecutive statements to different backend sessions and silently drop
# session-level state like `SET search_path`. See audit.py for the same note.

_TABLE = f"{db.SCHEMA}.recipients"

_PG_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    recipient_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '',
    notes TEXT
)
"""


def _pg_register(name: str, notes: Optional[str], aliases: list[str], dsn: str) -> str:
    recipient_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        conn.execute(
            f"INSERT INTO {_TABLE} (recipient_id, name, aliases, notes) VALUES (%s, %s, %s, %s)",
            (recipient_id, name, ",".join(aliases), notes),
        )
    return recipient_id


def _pg_list_all(dsn: str) -> list[dict]:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        rows = conn.execute(f"SELECT recipient_id, name, aliases, notes FROM {_TABLE}").fetchall()
    return [{"recipient_id": r[0], "name": r[1], "aliases": r[2], "notes": r[3]} for r in rows]


# --- public API ---------------------------------------------------------


def register(
    name: str, notes: Optional[str] = None, aliases: Optional[list[str]] = None, path: str = DEFAULT_DIRECTORY_PATH
) -> str:
    if db.is_postgres_dsn(path):
        return _pg_register(name, notes, aliases or [], path)
    return _local_register(name, notes, aliases or [], path)


def list_all(path: str = DEFAULT_DIRECTORY_PATH) -> list[dict]:
    if db.is_postgres_dsn(path):
        return _pg_list_all(path)
    return _local_list_all(path)


def _score(query: str, candidate: str) -> float:
    return difflib.SequenceMatcher(None, query.strip().lower(), candidate.strip().lower()).ratio()


def match_candidates(query: str, limit: int = 5, path: str = DEFAULT_DIRECTORY_PATH) -> list[Candidate]:
    scored = []
    for row in list_all(path):
        names_to_try = [row["name"]] + [a for a in row["aliases"].split(",") if a]
        best = max((_score(query, n) for n in names_to_try), default=0.0)
        if best > 0:
            scored.append(Candidate(recipient_id=row["recipient_id"], name=row["name"], score=round(best, 4)))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:limit]


def resolve(query: str, path: str = DEFAULT_DIRECTORY_PATH) -> Resolution:
    """Idempotent, read-only: safe to call before an interrupt() since it never writes."""
    candidates = match_candidates(query, path=path)
    if not candidates:
        return Resolution(status="none", candidates=[])

    top = candidates[0]
    runner_up_score = candidates[1].score if len(candidates) > 1 else 0.0
    if top.score >= EXACT_SCORE and (top.score - runner_up_score) > CLOSE_GAP:
        return Resolution(status="auto", candidates=candidates, recipient_id=top.recipient_id)
    if top.score >= CANDIDATE_SCORE:
        return Resolution(status="ambiguous", candidates=candidates)
    return Resolution(status="none", candidates=candidates)
