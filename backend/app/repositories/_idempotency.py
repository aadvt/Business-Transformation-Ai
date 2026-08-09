"""Shared idempotency-cache helper for endpoints whose target row has no
natural "already happened" marker of its own (settlement execute/confirm,
negotiation outcome). See app/db/models.py docstring for why this table
exists alongside approvals' own idempotency_key column."""

import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IdempotencyRecord
from app.schemas.money import utc_now


def idempotent(
    session: Session, key: str, endpoint: str, compute: Callable[[], dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """Returns (result, is_replay). Callers should skip one-time side effects
    (e.g. WS broadcasts) they'd otherwise perform when is_replay is True."""
    existing = session.execute(
        select(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing.response_payload, True

    result = compute()
    session.add(
        IdempotencyRecord(
            id=str(uuid.uuid4()), idempotency_key=key, endpoint=endpoint, response_payload=result, created_at=utc_now()
        )
    )
    session.flush()
    return result, False
