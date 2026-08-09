from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db_models import AgentRun, AuditLogEntry, DisruptionEvent
from app.deps import require_api_key
from app.schemas.audit import AuditEntry, AuditTrail
from app.schemas.enums import AgentName

router = APIRouter(prefix="/api/v1/audit", tags=["audit"], dependencies=[Depends(require_api_key)])


def _agent_or_none(value: str | None) -> AgentName | None:
    if not value:
        return None
    try:
        return AgentName(value)
    except ValueError:
        return None


@router.get("/{disruption_id}", response_model=AuditTrail)
async def get_audit_trail(disruption_id: str, db: AsyncSession = Depends(get_db)) -> AuditTrail:
    disruption = await db.get(DisruptionEvent, disruption_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Disruption not found")

    # The real schema correctly splits what the mock's AuditEntry lumped
    # together: audit_log is the governance/decision trail (human actions
    # included, hash-chained), agent_runs is agent execution telemetry.
    # Merged chronologically here into one timeline for this endpoint.
    audit_rows = (
        (
            await db.execute(
                select(AuditLogEntry).where(AuditLogEntry.disruption_id == disruption_id).order_by(AuditLogEntry.seq)
            )
        )
        .scalars()
        .all()
    )
    run_rows = (
        (await db.execute(select(AgentRun).where(AgentRun.disruption_id == disruption_id).order_by(AgentRun.started_at)))
        .scalars()
        .all()
    )

    entries = [
        AuditEntry(
            id=a.id,
            at=a.at.isoformat(),
            actor_type=a.actor_type,
            actor=a.actor,
            agent=_agent_or_none(a.actor) if a.actor_type == "AGENT" else None,
            action=a.action,
            detail=a.detail or {},
            prev_hash=a.prev_hash,
            hash=a.hash,
        )
        for a in audit_rows
    ]
    entries += [
        AuditEntry(
            id=r.id,
            at=(r.ended_at or r.started_at).isoformat(),
            actor_type="AGENT",
            actor=r.agent,
            agent=_agent_or_none(r.agent),
            action=f"AGENT_RUN_{r.status}",
            detail={"model_id": r.model_id, "latency_ms": r.latency_ms, "token_usage": r.token_usage},
            input_summary=r.input_summary,
            output_summary=r.output_summary,
        )
        for r in run_rows
    ]

    entries.sort(key=lambda e: e.at)
    return AuditTrail(disruption_id=disruption_id, entries=entries)
