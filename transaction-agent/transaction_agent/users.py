"""Local approver identity check: a small SQLite user table with salted,
hashed passphrases. Not enterprise auth (no sessions, no lockout policy,
no rotation) — just a real verification step in place of a free-text name.

    python -m transaction_agent.users create alice
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import closing

DEFAULT_USERS_PATH = os.environ.get("USERS_DB_PATH", "users.sqlite")

_ITERATIONS = 200_000
_ALGO = "sha256"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            salt TEXT NOT NULL,
            passphrase_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _hash(passphrase: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(_ALGO, passphrase.encode("utf-8"), salt, _ITERATIONS).hex()


def create_user(username: str, passphrase: str, path: str = DEFAULT_USERS_PATH, overwrite: bool = False) -> None:
    salt = secrets.token_bytes(16)
    digest = _hash(passphrase, salt)
    with closing(_connect(path)) as conn:
        if overwrite:
            conn.execute(
                "INSERT INTO users (username, salt, passphrase_hash) VALUES (?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, passphrase_hash=excluded.passphrase_hash",
                (username, salt.hex(), digest),
            )
        else:
            conn.execute(
                "INSERT INTO users (username, salt, passphrase_hash) VALUES (?, ?, ?)",
                (username, salt.hex(), digest),
            )
        conn.commit()


def verify(username: str, passphrase: str, path: str = DEFAULT_USERS_PATH) -> bool:
    if not username or not passphrase:
        return False
    with closing(_connect(path)) as conn:
        row = conn.execute(
            "SELECT salt, passphrase_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    if row is None:
        return False
    salt_hex, expected_hash = row
    actual_hash = _hash(passphrase, bytes.fromhex(salt_hex))
    return secrets.compare_digest(actual_hash, expected_hash)


def user_exists(username: str, path: str = DEFAULT_USERS_PATH) -> bool:
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
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
