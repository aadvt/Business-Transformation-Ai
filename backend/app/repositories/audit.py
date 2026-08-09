import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLogEntry, DisruptionEvent
from app.schemas.audit import AuditEntry, AuditTrail
from app.schemas.enums import AgentName
from app.schemas.money import to_iso

_AGENT_NAMES = {a.value for a in AgentName}


def _agent_for_entry(row: AuditLogEntry) -> AgentName:
    if row.actor_type == "AGENT" and row.actor in _AGENT_NAMES:
        return AgentName(row.actor)
    if row.actor_type == "HUMAN":
        return AgentName.GOVERNANCE
    return AgentName.SENTINEL


def _detail_text(row: AuditLogEntry) -> str:
    label = row.action.replace("_", " ").title()
    if not row.detail:
        return label
    fields = "; ".join(f"{k}={v}" for k, v in row.detail.items() if k != "note")
    note = row.detail.get("note")
    parts = [p for p in [note, fields] if p]
    return f"{label}: {'; '.join(parts)}" if parts else label


def disruption_exists(session: Session, disruption_id: str) -> bool:
    return session.get(DisruptionEvent, disruption_id) is not None


def get_trail(session: Session, disruption_id: str) -> AuditTrail:
    rows = session.execute(
        select(AuditLogEntry).where(AuditLogEntry.disruption_id == disruption_id).order_by(AuditLogEntry.seq)
    ).scalars().all()

    entries = [
        AuditEntry(
            id=row.id,
            at=to_iso(row.at),
            agent=_agent_for_entry(row),
            action=row.action,
            detail=_detail_text(row),
            input_summary=None,
            output_summary=json.dumps(row.detail)[:500] if row.detail else None,
        )
        for row in rows
    ]
    return AuditTrail(disruption_id=disruption_id, entries=entries)
