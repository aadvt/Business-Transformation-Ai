"""Server-side state for the voice channel, keyed by call_sid.

Deliberately never keyed by (or requiring the caller/LLM to restate) a
thread_id: Bolna's function-calling fills tool parameters from what its LLM
remembers of the conversation, and asking an LLM to correctly recall and
re-embed an opaque 36-character UUID turn after turn is a real, avoidable
failure mode. call_sid is different — Bolna auto-injects it into every tool
call via templating (e.g. %(call_sid)s), so it's never something the LLM
has to "remember" at all. Everything voice-specific hangs off call_sid here;
voice/adapter.py is the only thing that ever needs to know the thread_id.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from typing import Any, Optional

from transaction_agent.models import utcnow_iso

DEFAULT_VOICE_STATE_PATH = os.environ.get("VOICE_STATE_PATH", "voice_state.sqlite")


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS calls (
            call_sid TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pending_selections (
            call_sid TEXT PRIMARY KEY,
            selected_ids TEXT NOT NULL,
            total REAL NOT NULL,
            currency TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcripts (
            call_sid TEXT PRIMARY KEY,
            turns TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS disambiguation (
            call_sid TEXT PRIMARY KEY,
            current TEXT NOT NULL,
            remaining TEXT NOT NULL,
            choices TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return conn


def transcript_ref_for(call_sid: str) -> str:
    return f"voice_transcript:{call_sid}"


# --- call_sid -> thread_id -------------------------------------------------


def link_call(call_sid: str, thread_id: str, path: str = DEFAULT_VOICE_STATE_PATH) -> None:
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO calls (call_sid, thread_id, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(call_sid) DO UPDATE SET thread_id = excluded.thread_id",
            (call_sid, thread_id, utcnow_iso()),
        )
        conn.commit()


def get_thread_id(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> Optional[str]:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT thread_id FROM calls WHERE call_sid = ?", (call_sid,)).fetchone()
    return row[0] if row else None


# --- pending selection: set by /select, consumed (and cleared) by /confirm -


def set_pending_selection(
    call_sid: str, selected_ids: list[str], total: float, currency: str, path: str = DEFAULT_VOICE_STATE_PATH
) -> None:
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO pending_selections (call_sid, selected_ids, total, currency, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(call_sid) DO UPDATE SET selected_ids = excluded.selected_ids, "
            "total = excluded.total, currency = excluded.currency, created_at = excluded.created_at",
            (call_sid, json.dumps(selected_ids), total, currency, utcnow_iso()),
        )
        conn.commit()


def get_pending_selection(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> Optional[dict[str, Any]]:
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT selected_ids, total, currency FROM pending_selections WHERE call_sid = ?", (call_sid,)
        ).fetchone()
    if not row:
        return None
    return {"selected_ids": json.loads(row[0]), "total": row[1], "currency": row[2]}


def clear_pending_selection(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> None:
    with closing(_connect(path)) as conn:
        conn.execute("DELETE FROM pending_selections WHERE call_sid = ?", (call_sid,))
        conn.commit()


# --- transcript log: one growing record per call, referenced by audit entries


def append_transcript_turn(call_sid: str, speaker: str, text: str, path: str = DEFAULT_VOICE_STATE_PATH) -> None:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT turns FROM transcripts WHERE call_sid = ?", (call_sid,)).fetchone()
        turns = json.loads(row[0]) if row else []
        turns.append({"speaker": speaker, "text": text, "at": utcnow_iso()})
        conn.execute(
            "INSERT INTO transcripts (call_sid, turns) VALUES (?, ?) "
            "ON CONFLICT(call_sid) DO UPDATE SET turns = excluded.turns",
            (call_sid, json.dumps(turns)),
        )
        conn.commit()


def get_transcript(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> list[dict[str, Any]]:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT turns FROM transcripts WHERE call_sid = ?", (call_sid,)).fetchone()
    return json.loads(row[0]) if row else []


# --- recipient disambiguation: one item at a time over the phone -----------
#
# resolve_recipients_node batches every ambiguous/unknown recipient into a
# single interrupt. A voice call can't reasonably ask about all of them in
# one breath, so the adapter walks the list one item per turn, holding
# progress here, and only calls POST /requests/{id}/disambiguate once with
# every choice gathered, once the queue is empty.


def start_disambiguation(call_sid: str, pending_items: list[dict[str, Any]], path: str = DEFAULT_VOICE_STATE_PATH) -> dict[str, Any]:
    """Stores the full queue and returns the first item to ask about."""
    current, *remaining = pending_items
    with closing(_connect(path)) as conn:
        conn.execute(
            "INSERT INTO disambiguation (call_sid, current, remaining, choices) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(call_sid) DO UPDATE SET current = excluded.current, "
            "remaining = excluded.remaining, choices = excluded.choices",
            (call_sid, json.dumps(current), json.dumps(remaining), json.dumps({})),
        )
        conn.commit()
    return current


def get_current_disambiguation_item(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> Optional[dict[str, Any]]:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT current FROM disambiguation WHERE call_sid = ?", (call_sid,)).fetchone()
    return json.loads(row[0]) if row else None


def record_choice_and_advance(
    call_sid: str, transaction_id: str, choice: dict[str, Any], path: str = DEFAULT_VOICE_STATE_PATH
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Records the choice for the current item and advances the queue.

    Returns (next_item_or_None, all_choices_so_far). next_item is None once
    the queue is empty, meaning every pending recipient has been resolved.
    """
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT remaining, choices FROM disambiguation WHERE call_sid = ?", (call_sid,)).fetchone()
        remaining = json.loads(row[0]) if row else []
        choices = json.loads(row[1]) if row else {}
        choices[transaction_id] = choice

        next_item = None
        if remaining:
            next_item, *remaining = remaining

        conn.execute(
            "UPDATE disambiguation SET current = ?, remaining = ?, choices = ? WHERE call_sid = ?",
            (json.dumps(next_item), json.dumps(remaining), json.dumps(choices), call_sid),
        )
        conn.commit()
    return next_item, choices


def clear_disambiguation(call_sid: str, path: str = DEFAULT_VOICE_STATE_PATH) -> None:
    with closing(_connect(path)) as conn:
        conn.execute("DELETE FROM disambiguation WHERE call_sid = ?", (call_sid,))
        conn.commit()
