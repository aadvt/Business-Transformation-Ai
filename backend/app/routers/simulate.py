"""POST /api/v1/disruptions/simulate — dev-only, triggers a named seeded
golden-path scenario end-to-end up to AWAITING_APPROVAL. Gated on
`DEMO_MODE` (default true; set false in any real deployment).
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.sentinel import _OPEN_STAGES, SentinelAgent
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import DisruptionEvent, Vendor as VendorRow
from app.db.session import SessionLocal
from app.deps import require_api_key
from app.orchestrator.pipeline import run_pipeline_to_awaiting_approval

router = APIRouter(prefix="/api/v1/disruptions", tags=["simulate"], dependencies=[Depends(require_api_key)])

# scenario name -> (seeded vendor name, detector_name). The detector_name
# matters: some seeded vendors legitimately trip more than one detector (e.g.
# Bharat Casting Industries has both an overdue PO AND zero comm_events, so
# it trips both overdue_delivery and vendor_silence) — without pinning the
# detector, "most recently detected" could pick the wrong one for what the
# scenario name promises.
SCENARIOS: dict[str, tuple[str, str]] = {
    "delivery_delay_castings": ("Bharat Casting Industries", "overdue_delivery"),
    # Phase 4b: CRS-2MM's seeded inventory trend is already below reorder_point
    # by "now" (see app/seed.py) — TTM's zero-shot forecast picks this up via
    # app.agents.detectors.ttm_forecast.stockout_risk_ttm, attributed to the
    # vendor in SKU_VENDOR_HINTS. Falls back to a clear 422 if TTM didn't load.
    "stockout_risk": ("Marudhar Steel Traders", "ttm_stockout_forecast"),
}


class SimulateRequest(BaseModel):
    scenario: str


class SimulateResponse(BaseModel):
    disruption_id: str
    scenario: str
    stage: str
    newly_triggered: bool


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_disruption(body: SimulateRequest) -> SimulateResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")

    scenario_def = SCENARIOS.get(body.scenario)
    if scenario_def is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or not-yet-supported scenario '{body.scenario}'. Supported: {list(SCENARIOS)}",
        )
    vendor_name, detector_name = scenario_def

    with SessionLocal() as session:
        vendor = session.execute(
            select(VendorRow).where(VendorRow.org_id == DEFAULT_ORG_ID, VendorRow.name == vendor_name)
        ).scalar_one_or_none()
        if vendor is None:
            raise HTTPException(
                status_code=404,
                detail=f"Seed vendor '{vendor_name}' not found — run `python -m app.seed --reset` first.",
            )

        # Sync + blocking (DB, watsonx) — see pipeline.py's docstring on why
        # this must never run directly on the event loop.
        await asyncio.to_thread(SentinelAgent().run_once, session, DEFAULT_ORG_ID)

        disruption = session.execute(
            select(DisruptionEvent)
            .where(
                DisruptionEvent.vendor_id == vendor.id,
                DisruptionEvent.detector_name == detector_name,
                DisruptionEvent.stage.in_(_OPEN_STAGES),
            )
            .order_by(DisruptionEvent.detected_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if disruption is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Sentinel did not detect a '{detector_name}' signal for {vendor_name} — the golden-path "
                    "seed data may have been consumed by a prior run. Reseed with `python -m app.seed --reset`."
                ),
            )
        disruption_id = disruption.id
        stage = disruption.stage

    newly_triggered = stage == "DETECTED"
    if newly_triggered:
        await run_pipeline_to_awaiting_approval(DEFAULT_ORG_ID, disruption_id)
        with SessionLocal() as session:
            stage = session.get(DisruptionEvent, disruption_id).stage

    return SimulateResponse(
        disruption_id=disruption_id, scenario=body.scenario, stage=stage, newly_triggered=newly_triggered
    )
