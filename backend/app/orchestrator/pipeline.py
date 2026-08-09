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
from app.db.models import Approval as ApprovalRow, DisruptionEvent, VendorCandidate
from app.db.session import SessionLocal
from app.orchestrator.engine import IllegalTransitionError, transition
from app.schemas.enums import AgentName, AgentStatus, WSEventType
from app.schemas.money import utc_now
from app.services.audit import append_audit
from app.services.impact import get_or_build_impact_graph
from app.services.planner import build_plan
from app.services.agent_sheet import sync_sheet
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

        # Demo phase D1: build the blast-radius graph now that exposure/
        # diagnosis are on the row, and broadcast it — this is what makes the
        # frontend's canvas animate, so it has to fire during the run, not
        # only be available on request. Graph building is DB-only and fast,
        # but it's still sync SQLAlchemy, so it goes through asyncio.to_thread
        # same as every agent call (see this file's own docstring on why).
        impact_graph = await asyncio.to_thread(_compute_impact_and_audit, session, org_id, disruption)
        await live_feed.broadcast(
            WSEventType.IMPACT_COMPUTED, payload=impact_graph.model_dump(), disruption_id=disruption_id
        )

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

        # D5a: gspread is blocking and optional; keep the pipeline responsive.
        sync_result = await asyncio.to_thread(_sync_agent_sheet, org_id, disruption_id)
        await live_feed.broadcast(WSEventType.AGENT_SHEET_SYNCED, payload=sync_result, disruption_id=disruption_id)

        # D3: build remediation plan before approval (may not always succeed)
        candidates = session.query(VendorCandidate).filter_by(disruption_id=disruption_id).order_by(VendorCandidate.rank).all()
        plan_row = None
        if candidates:
            plan_row = await asyncio.to_thread(_build_and_persist_plan, session, disruption, candidates)
            if plan_row:
                await live_feed.broadcast(
                    WSEventType.PLAN_PROPOSED, payload={"plan_id": plan_row.id, "disruption_id": disruption_id}, disruption_id=disruption_id
                )

        approval_id = str(uuid.uuid4())
        now = utc_now()
        session.add(
            ApprovalRow(
                id=approval_id, disruption_id=disruption_id, status="PENDING", requested_at=now,
                decided_at=None, decided_by=None, channel=None, note=None,
                idempotency_key=None, presented_options=[plan_row.id] if plan_row else [],
            )
        )
        session.flush()

        transition(session, org_id, disruption, "AWAITING_APPROVAL", actor_type="AGENT", actor="ORCHESTRATOR")
        await _broadcast_stage(disruption)
        await live_feed.broadcast(
            WSEventType.APPROVAL_REQUESTED, payload={"approval_id": approval_id}, disruption_id=disruption_id
        )

        return sourcing_result

def _sync_agent_sheet(org_id: str, disruption_id: str) -> dict:
    with SessionLocal() as session:
        return sync_sheet(session, org_id, disruption_id)


def _compute_impact_and_audit(session, org_id: str, disruption: DisruptionEvent):
    """Sync (SQLAlchemy) — call only via asyncio.to_thread, see caller.

    One append_audit entry per impact computation, per CLAUDE.md's rule that
    append_audit is the only write path to audit_log — never construct
    AuditLogEntry directly.
    """
    graph = get_or_build_impact_graph(session, disruption)

    append_audit(
        session, org_id=org_id, disruption_id=disruption.id, actor_type="AGENT", actor="ORCHESTRATOR",
        action="IMPACT_COMPUTED",
        detail={
            "impacted_node_count": graph.summary.impacted_node_count,
            "at_risk_order_count": graph.summary.at_risk_order_count,
            "exposure_calc_id": graph.summary.exposure_calc_id,
        },
    )
    session.commit()
    return graph


def _build_and_persist_plan(session, disruption: DisruptionEvent, candidates: list[VendorCandidate]):
    """Sync (SQLAlchemy) — call only via asyncio.to_thread, see caller.

    Builds and persists a remediation plan. On any error, logs and returns None
    rather than failing the pipeline — planning is advisory, not blocking.
    """
    try:
        plan_row = build_plan(session, disruption, candidates)
        if plan_row:
            session.add(plan_row)
            session.flush()
            append_audit(
                session, org_id=disruption.org_id, disruption_id=disruption.id,
                actor_type="AGENT", actor="PLANNER",
                action="PLAN_CREATED",
                detail={
                    "plan_id": plan_row.id,
                    "solver": plan_row.solver,
                    "solve_ms": plan_row.solve_ms,
                    "requires_escalation": plan_row.requires_escalation,
                    "cost_to_resolve_paise": plan_row.cost_to_resolve_paise,
                    "net_saving_paise": plan_row.net_saving_paise,
                },
            )
            session.commit()
            return plan_row
    except Exception as e:
        logger.error(f"plan_creation_failed: {e}", extra={"disruption_id": disruption.id}, exc_info=True)
        session.rollback()
    return None


def _fail(session, org_id: str, disruption: DisruptionEvent, error: str | None) -> None:
    try:
        transition(session, org_id, disruption, "FAILED", actor_type="SYSTEM", actor="ORCHESTRATOR", note=error)
    except IllegalTransitionError:
        # FAILED isn't reachable from every stage in the table (e.g. AWAITING_APPROVAL
        # onward is human-gated) — if so, just log; the disruption stays where it is
        # rather than the orchestrator silently forcing an unmodeled state.
        logger.error("could_not_transition_to_failed", extra={"disruption_id": disruption.id, "stage": disruption.stage})
