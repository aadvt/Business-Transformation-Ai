"""Drives the default disruption flow from DETECTED to AWAITING_APPROVAL:
Diagnosis, then Sourcing, with a state-machine transition (and a WS broadcast)
between each step. Stops at AWAITING_APPROVAL because everything past that
point requires the human gate — see app.orchestrator.engine.

This is what backs `POST /api/v1/disruptions/simulate` (dev-only) and is where
Phase 4b/5 would hook in an automatic (non-simulate) trigger from Sentinel's
background loop, if that's ever wanted — deliberately not wired that way yet,
so a demo always progresses on a predictable, manually-triggered beat rather
than racing the 30s scheduler tick.
"""

import asyncio
import logging
import uuid

from app.agents.base import AgentContext, AgentResult
from app.agents.diagnosis import DiagnosisAgent
from app.agents.sourcing import SourcingAgent
from app.db.models import Approval as ApprovalRow, DisruptionEvent
from app.db.session import SessionLocal
from app.orchestrator.engine import IllegalTransitionError, transition
from app.schemas.enums import AgentName, AgentStatus, WSEventType
from app.schemas.money import utc_now
from app.ws_manager import live_feed

logger = logging.getLogger("sanjeevani.orchestrator")


async def _broadcast_stage(disruption: DisruptionEvent) -> None:
    await live_feed.broadcast(WSEventType.STAGE_CHANGED, payload={"stage": disruption.stage}, disruption_id=disruption.id)


async def _broadcast_agent_status(agent: AgentName, status: AgentStatus, disruption_id: str) -> None:
    await live_feed.broadcast(
        WSEventType.AGENT_STATUS_CHANGED,
        payload={"agent": agent.value, "status": status.value},
        disruption_id=disruption_id,
    )


async def run_pipeline_to_awaiting_approval(org_id: str, disruption_id: str) -> AgentResult:
    """Runs Diagnosis then Sourcing on `disruption_id`, transitioning
    DETECTED -> DIAGNOSED -> SOURCING -> AWAITING_APPROVAL. Returns the last
    agent's AgentResult; on failure the disruption is transitioned to FAILED
    instead of left in a stage that implies work is still happening.

    Each agent's `.run()` is fully synchronous (sync SQLAlchemy, blocking
    watsonx calls) and routed through `asyncio.to_thread` — without that, a
    multi-second agent call would stall the entire event loop, and every other
    request the server is handling, for its whole duration. The `session`
    object is only ever touched by one thread at a time (control doesn't
    return to this coroutine until the thread call finishes), so this is safe
    despite Session not being thread-safe for concurrent use.
    """
    with SessionLocal() as session:
        disruption = session.get(DisruptionEvent, disruption_id)
        if disruption is None:
            raise ValueError(f"No disruption {disruption_id}")

        await _broadcast_agent_status(AgentName.DIAGNOSIS, AgentStatus.RUNNING, disruption_id)
        diagnosis_result = await asyncio.to_thread(
            DiagnosisAgent().run, AgentContext(session=session, org_id=org_id, disruption_id=disruption_id)
        )
        await _broadcast_agent_status(
            AgentName.DIAGNOSIS, AgentStatus.DONE if diagnosis_result.ok else AgentStatus.ERROR, disruption_id
        )

        if not diagnosis_result.ok:
            _fail(session, org_id, disruption, diagnosis_result.error)
            await _broadcast_stage(disruption)
            return diagnosis_result

        transition(session, org_id, disruption, "DIAGNOSED", actor_type="AGENT", actor="DIAGNOSIS")
        await _broadcast_stage(disruption)

        transition(session, org_id, disruption, "SOURCING", actor_type="AGENT", actor="ORCHESTRATOR")
        await _broadcast_stage(disruption)

        await _broadcast_agent_status(AgentName.SOURCING, AgentStatus.RUNNING, disruption_id)
        sourcing_result = await asyncio.to_thread(
            SourcingAgent().run, AgentContext(session=session, org_id=org_id, disruption_id=disruption_id)
        )
        await _broadcast_agent_status(
            AgentName.SOURCING, AgentStatus.DONE if sourcing_result.ok else AgentStatus.ERROR, disruption_id
        )

        if not sourcing_result.ok:
            _fail(session, org_id, disruption, sourcing_result.error)
            await _broadcast_stage(disruption)
            return sourcing_result

        approval_id = str(uuid.uuid4())
        now = utc_now()
        session.add(
            ApprovalRow(
                id=approval_id, disruption_id=disruption_id, status="PENDING", requested_at=now,
                decided_at=None, decided_by=None, channel=None, note=None,
                idempotency_key=None, presented_options=[],
            )
        )
        session.flush()

        transition(session, org_id, disruption, "AWAITING_APPROVAL", actor_type="AGENT", actor="ORCHESTRATOR")
        await _broadcast_stage(disruption)
        await live_feed.broadcast(
            WSEventType.APPROVAL_REQUESTED, payload={"approval_id": approval_id}, disruption_id=disruption_id
        )

        return sourcing_result


def _fail(session, org_id: str, disruption: DisruptionEvent, error: str | None) -> None:
    try:
        transition(session, org_id, disruption, "FAILED", actor_type="SYSTEM", actor="ORCHESTRATOR", note=error)
    except IllegalTransitionError:
        # FAILED isn't reachable from every stage in the table (e.g. AWAITING_APPROVAL
        # onward is human-gated) — if so, just log; the disruption stays where it is
        # rather than the orchestrator silently forcing an unmodeled state.
        logger.error("could_not_transition_to_failed", extra={"disruption_id": disruption.id, "stage": disruption.stage})
