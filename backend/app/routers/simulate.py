"""POST /api/v1/disruptions/simulate — dev-only, triggers a disruption
end-to-end up to AWAITING_APPROVAL, either from a named seeded golden-path
scenario (Phase 4a/4b) or, as of Demo phase D0, from an arbitrary seeded
vendor + ScenarioKind so the frontend's trigger modal isn't limited to the
two golden paths. Gated on `DEMO_MODE` (default true; set false in any real
deployment).

GET /api/v1/simulate/targets — lists vendors that make good demo targets, so
the frontend can populate its trigger modal without anyone pasting a UUID on
stage.
"""

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.sentinel import _already_open, _OPEN_STAGES, SentinelAgent
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import DisruptionEvent, PurchaseOrder, Vendor as VendorRow
from app.db.session import SessionLocal
from app.deps import require_api_key
from app.orchestrator.pipeline import run_pipeline_to_awaiting_approval
from app.schemas.enums import DisruptionType, ScenarioKind
from app.schemas.money import utc_now
from app.services.audit import append_audit
from app.services.exposure import AffectedPO, compute_exposure

router = APIRouter(prefix="/api/v1", tags=["simulate"], dependencies=[Depends(require_api_key)])

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

# Demo phase D0: kind -> DisruptionType for the free-form vendor_id+kind path.
KIND_TO_DISRUPTION_TYPE: dict[ScenarioKind, DisruptionType] = {
    ScenarioKind.BACKED_OUT: DisruptionType.VENDOR_UNRESPONSIVE,
    ScenarioKind.PRICE_HIKE: DisruptionType.PRICE_SHOCK,
    ScenarioKind.DELAYED: DisruptionType.DELIVERY_DELAY,
    ScenarioKind.SHUT_DOWN: DisruptionType.VENDOR_UNRESPONSIVE,
}

# Distinct from every rule-based detector name so dedup (_already_open) never
# collides with a real Sentinel-raised signal for the same vendor.
MANUAL_TRIGGER_DETECTOR = "demo_manual_trigger"

_HEADLINE_BY_KIND: dict[ScenarioKind, str] = {
    ScenarioKind.BACKED_OUT: "{vendor} has gone unresponsive and backed out of committed orders",
    ScenarioKind.PRICE_HIKE: "{vendor} has announced a sudden price increase on active orders",
    ScenarioKind.DELAYED: "{vendor} has delayed delivery on open purchase orders",
    ScenarioKind.SHUT_DOWN: "{vendor} appears to have shut down operations — no response on open orders",
}


def _headline_for_kind(kind: ScenarioKind, vendor_name: str) -> str:
    return _HEADLINE_BY_KIND[kind].format(vendor=vendor_name)[:90]


class SimulateRequest(BaseModel):
    # Backward-compatible golden-path trigger — unchanged since Phase 4a.
    scenario: str | None = None
    # Demo phase D0: free-form trigger against any seeded vendor. Both
    # vendor_id and kind must be supplied together; scenario takes priority
    # if both are present.
    vendor_id: str | None = None
    kind: ScenarioKind | None = None
    effective_date: str | None = None


class SimulateResponse(BaseModel):
    disruption_id: str
    scenario: str
    stage: str
    newly_triggered: bool


class SimulateTarget(BaseModel):
    vendor_id: str
    name: str
    category: str
    open_po_count: int
    downstream_line_count: int
    est_exposure_paise: int
    recommended_kinds: list[ScenarioKind]


class SimulateTargetsResponse(BaseModel):
    items: list[SimulateTarget]


@router.post("/disruptions/simulate", response_model=SimulateResponse)
async def simulate_disruption(body: SimulateRequest) -> SimulateResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")

    if body.scenario is not None:
        return await _simulate_scenario(body.scenario)
    if body.vendor_id is not None and body.kind is not None:
        return await _simulate_custom(body.vendor_id, body.kind, body.effective_date)
    raise HTTPException(
        status_code=422,
        detail="Provide either 'scenario', or both 'vendor_id' and 'kind'.",
    )


async def _simulate_scenario(scenario: str) -> SimulateResponse:
    scenario_def = SCENARIOS.get(scenario)
    if scenario_def is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or not-yet-supported scenario '{scenario}'. Supported: {list(SCENARIOS)}",
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

    return SimulateResponse(disruption_id=disruption_id, scenario=scenario, stage=stage, newly_triggered=newly_triggered)


async def _simulate_custom(vendor_id: str, kind: ScenarioKind, effective_date: str | None) -> SimulateResponse:
    def _get_or_create() -> tuple[str, str, bool]:
        with SessionLocal() as session:
            vendor = session.execute(
                select(VendorRow).where(VendorRow.id == vendor_id, VendorRow.org_id == DEFAULT_ORG_ID)
            ).scalar_one_or_none()
            if vendor is None:
                raise HTTPException(status_code=404, detail=f"Vendor '{vendor_id}' not found.")

            if _already_open(session, vendor.id, MANUAL_TRIGGER_DETECTOR):
                existing = session.execute(
                    select(DisruptionEvent)
                    .where(
                        DisruptionEvent.vendor_id == vendor.id,
                        DisruptionEvent.detector_name == MANUAL_TRIGGER_DETECTOR,
                        DisruptionEvent.stage.in_(_OPEN_STAGES),
                    )
                    .order_by(DisruptionEvent.detected_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                return existing.id, existing.stage, False

            disruption_type = KIND_TO_DISRUPTION_TYPE[kind]
            headline = _headline_for_kind(kind, vendor.name)
            disruption_id = str(uuid.uuid4())
            now = utc_now()

            # The vendor's undelivered POs are what this disruption actually
            # puts at risk. Without them the disruption carries no affected
            # POs, so Diagnosis computes ₹0 exposure and the planner returns
            # None (it has nothing to re-source) — the whole downstream demo
            # collapses to zeroes. This is deliberately the same PO set
            # GET /simulate/targets estimates from, so the exposure the modal
            # previewed is the exposure the disruption reports.
            open_po_ids = list(
                session.execute(
                    select(PurchaseOrder.id).where(
                        PurchaseOrder.vendor_id == vendor.id, PurchaseOrder.delivered_at.is_(None)
                    )
                ).scalars().all()
            )

            evidence = {
                "kind": kind.value,
                "effective_date": effective_date,
                "triggered_via": "demo_simulate",
                "open_po_count": len(open_po_ids),
            }
            session.add(
                DisruptionEvent(
                    id=disruption_id,
                    org_id=DEFAULT_ORG_ID,
                    type=disruption_type.value,
                    stage="DETECTED",
                    vendor_id=vendor.id,
                    detected_at=now,
                    headline=headline,
                    signal_payload=evidence,
                    detector_name=MANUAL_TRIGGER_DETECTOR,
                    detector_source="RULE_BASED",
                    affected_po_ids=open_po_ids,
                )
            )
            session.flush()
            append_audit(
                session, org_id=DEFAULT_ORG_ID, disruption_id=disruption_id, actor_type="SYSTEM",
                actor="DEMO_SIMULATE", action="SIGNAL_RAISED",
                detail={"detector_name": MANUAL_TRIGGER_DETECTOR, "vendor_id": vendor.id, **evidence}, at=now,
            )
            session.commit()
            return disruption_id, "DETECTED", True

    disruption_id, stage, newly_triggered = await asyncio.to_thread(_get_or_create)

    if newly_triggered:
        await run_pipeline_to_awaiting_approval(DEFAULT_ORG_ID, disruption_id)
        with SessionLocal() as session:
            stage = session.get(DisruptionEvent, disruption_id).stage

    return SimulateResponse(
        disruption_id=disruption_id, scenario=f"custom:{kind.value}", stage=stage, newly_triggered=newly_triggered
    )


@router.get("/simulate/targets", response_model=SimulateTargetsResponse)
async def simulate_targets() -> SimulateTargetsResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")

    def _build() -> list[SimulateTarget]:
        with SessionLocal() as session:
            vendors = session.execute(select(VendorRow).where(VendorRow.org_id == DEFAULT_ORG_ID)).scalars().all()

            # Two queries total, not one per vendor. This endpoint is the very
            # first thing the demo operator hits (it populates the trigger
            # modal), and a per-vendor query was ~24 Neon round-trips — about
            # 11 seconds of loading skeleton before the dialog was usable.
            pos_by_vendor: dict[str, list[PurchaseOrder]] = {}
            all_open_pos = session.execute(
                select(PurchaseOrder).where(
                    PurchaseOrder.org_id == DEFAULT_ORG_ID, PurchaseOrder.delivered_at.is_(None)
                )
            ).scalars().all()
            for po in all_open_pos:
                pos_by_vendor.setdefault(po.vendor_id, []).append(po)

            targets: list[SimulateTarget] = []
            for vendor in vendors:
                open_pos = pos_by_vendor.get(vendor.id, [])
                if not open_pos:
                    continue

                downstream_line_count = sum(1 for po in open_pos if po.downstream_order_ref is not None)
                affected = [
                    AffectedPO(
                        po_id=po.id, po_number=po.po_number, undelivered_qty=po.qty,
                        unit_price_paise=po.unit_price_paise, downstream_order_ref=po.downstream_order_ref,
                        downstream_order_value_paise=po.downstream_order_value_paise,
                        penalty_rate_bps=po.penalty_rate_bps,
                    )
                    for po in open_pos
                ]
                exposure = compute_exposure(affected)

                targets.append(
                    SimulateTarget(
                        vendor_id=vendor.id, name=vendor.name, category=vendor.category,
                        open_po_count=len(open_pos), downstream_line_count=downstream_line_count,
                        est_exposure_paise=exposure.total_paise, recommended_kinds=list(ScenarioKind),
                    )
                )

            targets.sort(key=lambda t: t.est_exposure_paise, reverse=True)
            return targets[:10]

    return SimulateTargetsResponse(items=await asyncio.to_thread(_build))
