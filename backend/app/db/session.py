"""Engine + session factory.

Two engines can exist: the app's pooled engine (DATABASE_URL, tuned for Neon's
serverless pooler) and a direct engine used only by schema-creation/seed
scripts (DATABASE_URL_DIRECT). Both also accept a sqlite URL for the offline
fallback — see README.md "Offline / no-Postgres fallback".
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _make_engine(url: str, *, pooled: bool) -> Engine:
    is_sqlite = url.startswith("sqlite")
    kwargs: dict = {"pool_pre_ping": True}
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    elif pooled:
        # Neon scales its compute to zero after ~5 min idle; pool_pre_ping detects a
        # stale/dropped connection and transparently reconnects instead of a 500.
        kwargs["pool_size"] = 5
        kwargs["max_overflow"] = 5
        kwargs["pool_recycle"] = 300
        # The pooled endpoint is PgBouncer in transaction mode, which doesn't
        # support server-side prepared statements persisting across pooled
        # connections. psycopg3 auto-prepares repeated statements by
        # default; against a transaction-mode pooler that surfaces as
        # intermittent "prepared statement does not exist" errors under
        # concurrent load. Only applies to the pooled engine — the direct
        # engine (seed/create_all, not pooled) doesn't need it.
        kwargs["connect_args"] = {"prepare_threshold": None}
    return create_engine(url, **kwargs)


engine: Engine = _make_engine(settings.database_url, pooled=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_direct_engine() -> Engine:
    """Non-pooled engine for create_all / seed scripts only — never used to serve requests."""
    return _make_engine(settings.database_url_direct_resolved, pooled=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connectivity() -> float:
    """Runs a blocking SELECT 1 and returns round-trip time in milliseconds.

    Called once at app startup so a cold Neon compute (scaled to zero) shows up
    clearly in logs as a slow first connection, instead of silently costing the
    first real request.
    """
    start = time.monotonic()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return (time.monotonic() - start) * 1000
