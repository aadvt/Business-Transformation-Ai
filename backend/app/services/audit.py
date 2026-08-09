"""Append-only, hash-chained audit log.

This is our stand-in for watsonx.governance's audit trail: every agent/human/
system action that matters gets one row, and each row's hash commits to the
previous row's hash plus its own content, so any row edited after the fact
breaks the chain. `append_audit` is the ONLY write path — never construct an
AuditLogEntry directly.

Chain scope: entries tied to a disruption (`disruption_id` set) form their own
per-disruption chain starting at seq=1. Entries not tied to any disruption
(`disruption_id=None`, e.g. system-level events) form one chain per org.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLogEntry
from app.schemas.money import to_iso, utc_now

GENESIS_HASH = "0" * 64


def _canonical_json(obj: dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _row_payload(
    *,
    id: str,
    org_id: str,
    disruption_id: str | None,
    seq: int,
    at: datetime,
    actor_type: str,
    actor: str,
    action: str,
    detail: dict,
    prev_hash: str,
) -> dict[str, Any]:
    return {
        "id": id,
        "org_id": org_id,
        "disruption_id": disruption_id,
        "seq": seq,
        "at": to_iso(at),
        "actor_type": actor_type,
        "actor": actor,
        "action": action,
        "detail": detail,
        "prev_hash": prev_hash,
    }


def append_audit(
    session: Session,
    *,
    org_id: str,
    actor_type: str,
    actor: str,
    action: str,
    disruption_id: str | None = None,
    detail: dict | None = None,
    at: datetime | None = None,
) -> AuditLogEntry:
    detail = detail or {}
    at = at or utc_now()

    scope_filter = (
        AuditLogEntry.disruption_id == disruption_id
        if disruption_id is not None
        else (AuditLogEntry.disruption_id.is_(None) & (AuditLogEntry.org_id == org_id))
    )
    last_row = (
        session.execute(select(AuditLogEntry).where(scope_filter).order_by(AuditLogEntry.seq.desc()).limit(1))
        .scalars()
        .first()
    )

    if last_row is None:
        seq, prev_hash = 1, GENESIS_HASH
    else:
        seq, prev_hash = last_row.seq + 1, last_row.hash

    entry_id = str(uuid.uuid4())
    payload = _row_payload(
        id=entry_id,
        org_id=org_id,
        disruption_id=disruption_id,
        seq=seq,
        at=at,
        actor_type=actor_type,
        actor=actor,
        action=action,
        detail=detail,
        prev_hash=prev_hash,
    )
    computed_hash = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    entry = AuditLogEntry(
        id=entry_id,
        org_id=org_id,
        disruption_id=disruption_id,
        seq=seq,
        at=at,
        actor_type=actor_type,
        actor=actor,
        action=action,
        detail=detail,
        prev_hash=prev_hash,
        hash=computed_hash,
    )
    session.add(entry)
    session.flush()
    return entry


@dataclass(frozen=True)
class AuditChainResult:
    ok: bool
    broken_at: int | None


def verify_audit_chain(session: Session, disruption_id: str) -> AuditChainResult:
    rows = (
        session.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.disruption_id == disruption_id)
            .order_by(AuditLogEntry.seq)
        )
        .scalars()
        .all()
    )

    prev_hash = GENESIS_HASH
    for row in rows:
        if row.prev_hash != prev_hash:
            return AuditChainResult(ok=False, broken_at=row.seq)

        payload = _row_payload(
            id=row.id,
            org_id=row.org_id,
            disruption_id=row.disruption_id,
            seq=row.seq,
            at=row.at,
            actor_type=row.actor_type,
            actor=row.actor,
            action=row.action,
            detail=row.detail,
            prev_hash=row.prev_hash,
        )
        expected_hash = sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        if expected_hash != row.hash:
            return AuditChainResult(ok=False, broken_at=row.seq)

        prev_hash = row.hash

    return AuditChainResult(ok=True, broken_at=None)
