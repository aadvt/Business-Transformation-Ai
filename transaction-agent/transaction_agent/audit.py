"""Persistent audit log: append-only JSON store of every state transition.

Writes are idempotent (deduped by entry_id) because log_node runs once per
transaction inside a LangGraph map-reduce fan-out, and a swappable backend
(e.g. SQLite) could reasonably be flushed more than once for the same
entries during retries.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", "audit_log.json")

_lock = threading.Lock()


def _read(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return []
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, entries: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)
    tmp.replace(p)


def append_entries(
    entries: list[dict[str, Any]], path: str = DEFAULT_AUDIT_LOG_PATH
) -> list[dict[str, Any]]:
    """Append entries to the persistent log, skipping any entry_id already present.

    Returns the subset of entries that were actually newly written.
    """
    if not entries:
        return []
    with _lock:
        existing = _read(path)
        existing_ids = {e.get("entry_id") for e in existing}
        fresh = [e for e in entries if e.get("entry_id") not in existing_ids]
        if fresh:
            existing.extend(fresh)
            _write(path, existing)
        return fresh


def read_all(path: str = DEFAULT_AUDIT_LOG_PATH) -> list[dict[str, Any]]:
    with _lock:
        return _read(path)


def clear(path: str = DEFAULT_AUDIT_LOG_PATH) -> None:
    with _lock:
        if Path(path).exists():
            Path(path).unlink()
