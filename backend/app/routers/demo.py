"""Demo control plane — dev-only endpoints for resetting/inspecting the demo
dataset without restarting the server. Gated on `settings.demo_mode`, same as
`POST /disruptions/simulate` (see app/routers/simulate.py, CLAUDE.md).

`POST /demo/reset` deliberately does NOT touch the schema (no drop_all/
create_all) — CLAUDE.md documents that path deadlocking against a running
server (DROP TABLE needs an ACCESS EXCLUSIVE lock that the pooled connections
and the background Sentinel loop hold). Instead it deletes rows from the
disruption-lifecycle tables only (vendors/POs/inventory/comm_events/
settlement_batches are untouched) and re-seeds the three legacy golden-path
disruptions via app.seed's own (tested) `_seed_legacy_disruptions`, so the
result is byte-for-byte the same shape `python -m app.seed --reset` produces
for those rows, just without the schema rebuild or the 20k-row vendor/PO/
inventory regeneration.
"""

import time
from random import Random

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.agents.detectors import ttm_forecast
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import (
    AgentRun,
    AgentSheetSync as AgentSheetSyncRow,
    Approval,
    AuditLogEntry,
    CallSession,
    DisruptionEvent,
    ExposureCalc,
    Negotiation,
    RemediationPlanRow,
    Vendor as VendorRow,
    VendorCandidate,
    Verification,
)
from app.db.session import SessionLocal, check_connectivity
from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.common import ApiModel
from app.schemas.enums import DisruptionStage, IntegrationStatus
from app.schemas.money import utc_now, utc_now_iso
from app.seed import SEED, _seed_legacy_disruptions
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1/demo", tags=["demo"], dependencies=[Depends(require_api_key)])

# Children before parents — FK constraints are enforced on Postgres (Neon),
# even though sqlite (the offline fallback) doesn't check them by default.
# Verification isn't in the brief's literal list but has a FK to
# disruption_events.id, so it has to go too or the DisruptionEvent delete
# fails on Postgres with a row still referencing it.
_TABLES_TO_CLEAR: list[tuple[str, type]] = [
    ("agent_runs", AgentRun),
    ("audit_log", AuditLogEntry),
    ("call_sessions", CallSession),
    ("remediation_plans", RemediationPlanRow),
    ("agent_sheet_syncs", AgentSheetSyncRow),
    ("vendor_candidates", VendorCandidate),
    ("verifications", Verification),
    ("negotiations", Negotiation),
    ("approvals", Approval),
    ("exposure_calcs", ExposureCalc),
    ("disruption_events", DisruptionEvent),
]


class DemoResetResponse(ApiModel):
    cleared: dict[str, int]
    reseeded_disruptions: int
    elapsed_ms: float


class DemoStageCount(ApiModel):
    stage: DisruptionStage
    count: int


class DemoState(ApiModel):
    disruption_count_by_stage: list[DemoStageCount]
    integrations: dict[str, IntegrationStatus]
    ttm_loaded: bool
    ws_client_count: int
    db_roundtrip_ms: float
    updated_at: str


def _require_demo_mode() -> None:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/reset", response_model=DemoResetResponse)
async def demo_reset() -> DemoResetResponse:
    _require_demo_mode()
    start = time.monotonic()
    cleared: dict[str, int] = {}

    with SessionLocal() as session:
        for label, model in _TABLES_TO_CLEAR:
            count = session.execute(select(func.count()).select_from(model)).scalar_one()
            session.execute(delete(model))
            cleared[label] = count

        vendor_by_id = {
            v.id: v
            for v in session.execute(select(VendorRow).where(VendorRow.org_id == DEFAULT_ORG_ID)).scalars().all()
        }
        _seed_legacy_disruptions(session, Random(SEED), utc_now(), vendor_by_id)
        session.commit()

    cleared["ws_ring_buffer"] = len(live_feed.replay_buffer())
    live_feed.clear_buffer()

    return DemoResetResponse(
        cleared=cleared, reseeded_disruptions=3, elapsed_ms=round((time.monotonic() - start) * 1000, 1)
    )


@router.get("/state", response_model=DemoState)
async def demo_state() -> DemoState:
    _require_demo_mode()

    with SessionLocal() as session:
        rows = session.execute(
            select(DisruptionEvent.stage, func.count()).group_by(DisruptionEvent.stage)
        ).all()
    stage_counts = [DemoStageCount(stage=stage, count=count) for stage, count in rows]

    try:
        db_roundtrip_ms = round(check_connectivity(), 1)
    except Exception:
        db_roundtrip_ms = -1.0

    return DemoState(
        disruption_count_by_stage=stage_counts,
        integrations=store.metrics_demo.integrations.model_dump(),
        ttm_loaded=ttm_forecast.is_available(),
        ws_client_count=live_feed.connection_count,
        db_roundtrip_ms=db_roundtrip_ms,
        updated_at=utc_now_iso(),
    )
