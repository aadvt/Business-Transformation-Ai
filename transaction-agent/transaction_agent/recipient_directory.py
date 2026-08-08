"""Local recipient directory: SQLite table of known payees, fuzzy-matched
against parsed transaction recipients so recipient_id can be filled in
automatically for a clean match, or routed to a human for disambiguation
otherwise.

Not a production identity system — no dedup merging, no admin UI. Just
enough to make recipient_id something other than always-null.
"""

from __future__ import annotations

import difflib
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from typing import Optional

DEFAULT_DIRECTORY_PATH = os.environ.get("RECIPIENT_DIRECTORY_PATH", "recipient_directory.sqlite")

EXACT_SCORE = 0.90
CANDIDATE_SCORE = 0.55
CLOSE_GAP = 0.08


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recipients (
            recipient_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            aliases TEXT NOT NULL DEFAULT '',
            notes TEXT
        )
        """
    )
    conn.commit()
    return conn


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


def register(name: str, notes: Optional[str] = None, aliases: Optional[list[str]] = None, path: str = DEFAULT_DIRECTORY_PATH) -> str:
    recipient_id = f"rcpt_{uuid.uuid4().hex[:12]}"
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO recipients (recipient_id, name, aliases, notes) VALUES (?, ?, ?, ?)",
            (recipient_id, name, ",".join(aliases or []), notes),
        )
        conn.commit()
    return recipient_id


def list_all(path: str = DEFAULT_DIRECTORY_PATH) -> list[dict]:
    with closing(_connect(path)) as conn:
        rows = conn.execute("SELECT recipient_id, name, aliases, notes FROM recipients").fetchall()
    return [{"recipient_id": r[0], "name": r[1], "aliases": r[2], "notes": r[3]} for r in rows]


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
