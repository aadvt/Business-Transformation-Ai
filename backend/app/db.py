"""Async SQLAlchemy engine/session for the Neon Postgres backend.

Two things here will silently misbehave in production-shaped ways if
skipped — both learned by testing against the real Neon endpoints, not
assumed:

1. Neon's pooled connection string routes through PgBouncer in transaction
   mode, which does not support server-side prepared statements persisting
   across pooled connections. psycopg3 prepares statements after a
   threshold of repeated use by default; against a transaction-mode pooler
   that surfaces as intermittent "prepared statement does not exist" errors
   under load. `prepare_threshold=None` in connect_args disables this.
2. Async SQLAlchemy does not lazy-load relationships across await
   boundaries safely — every relationship a router needs must be
   eager-loaded (selectinload/joinedload) in the query itself. See
   app/db_models.py and the routers for where this matters.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _to_async_dsn(url: str) -> str:
    """Accepts a plain postgresql:// URL (as Neon hands out) and returns the
    postgresql+psycopg:// form SQLAlchemy needs to pick the async psycopg3
    dialect."""
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


engine = create_async_engine(
    _to_async_dsn(settings.database_url),
    pool_pre_ping=True,  # Neon serverless suspends on idle; this survives the cold-start reconnect
    connect_args={"prepare_threshold": None},  # see module docstring, point 1
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
