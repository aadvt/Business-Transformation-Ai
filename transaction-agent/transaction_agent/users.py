"""Local approver identity check: a user table with salted, hashed
passphrases. Not enterprise auth (no sessions, no lockout policy, no
rotation) — just a real verification step in place of a free-text name.

    python -m transaction_agent.users create alice

Two backends behind the same functions, selected by what `path` looks
like: a local file path uses SQLite (default — zero external dependencies,
what the test suite uses), a `postgres://`/`postgresql://` connection
string uses Postgres (Neon) instead, in the "transaction_agent" schema.
DEFAULT_USERS_PATH picks Postgres automatically when DATABASE_URL is set,
so production usage gets it for free without every call site changing.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import closing
from typing import Optional

from . import db

DEFAULT_USERS_PATH = os.environ.get("DATABASE_URL") or os.environ.get("USERS_DB_PATH", "users.sqlite")

_ITERATIONS = 200_000
_ALGO = "sha256"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    passphrase_hash TEXT NOT NULL
)
"""


def _hash(passphrase: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(_ALGO, passphrase.encode("utf-8"), salt, _ITERATIONS).hex()


# --- local SQLite backend ----------------------------------------------


def _sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _local_create_user(username: str, salt_hex: str, digest: str, path: str, overwrite: bool) -> None:
    with closing(_sqlite_connect(path)) as conn:
        if overwrite:
            conn.execute(
                "INSERT INTO users (username, salt, passphrase_hash) VALUES (?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, passphrase_hash=excluded.passphrase_hash",
                (username, salt_hex, digest),
            )
        else:
            conn.execute("INSERT INTO users (username, salt, passphrase_hash) VALUES (?, ?, ?)", (username, salt_hex, digest))
        conn.commit()


def _local_lookup(username: str, path: str) -> Optional[tuple[str, str]]:
    with closing(_sqlite_connect(path)) as conn:
        row = conn.execute("SELECT salt, passphrase_hash FROM users WHERE username = ?", (username,)).fetchone()
    return tuple(row) if row else None


# --- Postgres (Neon) backend ---------------------------------------------
#
# Schema-qualified (transaction_agent.users) rather than relying on
# search_path — DATABASE_URL is Neon's pooled endpoint, which can hand
# consecutive statements to different backend sessions and silently drop
# session-level state like `SET search_path`. Also avoids any collision
# with a "users" table this database's other services (e.g. this project's
# own backend/) might have in the "public" schema.

_TABLE = f"{db.SCHEMA}.users"

_PG_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    username TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    passphrase_hash TEXT NOT NULL
)
"""


def _pg_create_user(username: str, salt_hex: str, digest: str, dsn: str, overwrite: bool) -> None:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        if overwrite:
            conn.execute(
                f"INSERT INTO {_TABLE} (username, salt, passphrase_hash) VALUES (%s, %s, %s) "
                "ON CONFLICT (username) DO UPDATE SET salt = excluded.salt, passphrase_hash = excluded.passphrase_hash",
                (username, salt_hex, digest),
            )
        else:
            conn.execute(f"INSERT INTO {_TABLE} (username, salt, passphrase_hash) VALUES (%s, %s, %s)", (username, salt_hex, digest))


def _pg_lookup(username: str, dsn: str) -> Optional[tuple[str, str]]:
    with db.connect(dsn) as conn:
        conn.execute(_PG_CREATE_TABLE)
        row = conn.execute(f"SELECT salt, passphrase_hash FROM {_TABLE} WHERE username = %s", (username,)).fetchone()
    return tuple(row) if row else None


# --- public API ---------------------------------------------------------


def create_user(username: str, passphrase: str, path: str = DEFAULT_USERS_PATH, overwrite: bool = False) -> None:
    salt = secrets.token_bytes(16)
    digest = _hash(passphrase, salt)
    if db.is_postgres_dsn(path):
        _pg_create_user(username, salt.hex(), digest, path, overwrite)
    else:
        _local_create_user(username, salt.hex(), digest, path, overwrite)


def verify(username: str, passphrase: str, path: str = DEFAULT_USERS_PATH) -> bool:
    if not username or not passphrase:
        return False
    row = _pg_lookup(username, path) if db.is_postgres_dsn(path) else _local_lookup(username, path)
    if row is None:
        return False
    salt_hex, expected_hash = row
    actual_hash = _hash(passphrase, bytes.fromhex(salt_hex))
    return secrets.compare_digest(actual_hash, expected_hash)


def user_exists(username: str, path: str = DEFAULT_USERS_PATH) -> bool:
    row = _pg_lookup(username, path) if db.is_postgres_dsn(path) else _local_lookup(username, path)
    return row is not None


def _main() -> int:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Manage local approver users")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create (or overwrite) a user")
    create.add_argument("username")
    create.add_argument("--passphrase", default=None, help="Non-interactive; omit to be prompted securely")
    create.add_argument("--path", default=DEFAULT_USERS_PATH)
    create.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()
    if args.command == "create":
        passphrase = args.passphrase or getpass.getpass("Passphrase: ")
        create_user(args.username, passphrase, path=args.path, overwrite=args.overwrite)
        print(f"Created user '{args.username}' in {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
