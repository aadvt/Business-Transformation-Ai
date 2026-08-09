"""DB-backed idempotency, replacing the four in-memory dicts the mock phase
used (app/mocks/loader.py's *_idempotency dicts) — same replay-the-cached-
response pattern, but now surviving a process restart, since
idempotency_records is a real table with a unique index on
idempotency_key.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_models import IdempotencyRecord
from app.schemas.money import utc_now


async def get_cached_response(db: AsyncSession, idempotency_key: str) -> dict | None:
    result = await db.execute(select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == idempotency_key))
    record = result.scalar_one_or_none()
    return record.response_payload if record is not None else None


async def store_response(db: AsyncSession, idempotency_key: str, endpoint: str, payload: dict) -> None:
    db.add(
        IdempotencyRecord(
            id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            response_payload=payload,
            created_at=utc_now(),
        )
    )
    await db.commit()
