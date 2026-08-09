"""Open the right LangGraph checkpointer: Postgres (Neon) when a direct
connection string is configured, SQLite otherwise. Shared by cli.py and
api.py so both front ends pick a backend the same way, mirroring how
audit.py/recipient_directory.py/users.py pick Postgres automatically when
DATABASE_URL is set.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from . import db

# Distinguishes "caller didn't specify postgres_dsn, use the env default"
# from "caller explicitly passed None to force SQLite" — a plain `None`
# default couldn't tell those apart, which was a real bug: Settings
# dataclasses (api.py) always pass an explicit value (possibly None, e.g.
# from tests wanting SQLite), while cli.py only wants the env fallback when
# its --checkpoint-dsn flag was never given.
_UNSET = object()


def open_checkpointer(sqlite_path: str, postgres_dsn: Optional[str] = _UNSET):
    """Returns (connection, saver). The caller owns the connection's
    lifecycle (close it when done) exactly as with a plain SqliteSaver."""
    if postgres_dsn is _UNSET:
        postgres_dsn = os.environ.get("DATABASE_URL_DIRECT")

    if postgres_dsn:
        from langgraph.checkpoint.postgres import PostgresSaver

        conn = db.connect_for_checkpointer(postgres_dsn)
        saver = PostgresSaver(conn)
        saver.setup()
        return conn, saver

    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return conn, saver
