from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import disruptions as repo
from app.schemas.disruptions import Disruption, DisruptionList, DisruptionSummary
from app.schemas.enums import DisruptionStage
from app.schemas.impact import ImpactGraph
from app.schemas.planner import PlanDiffResponse
from app.services.impact import get_or_build_impact_graph
from app.db.models import RemediationPlanRow

router = APIRouter(prefix="/api/v1/disruptions", tags=["disruptions"], dependencies=[Depends(require_api_key)])


def _list_disruptions_mock(stage: DisruptionStage | None, limit: int) -> DisruptionList:
    items = list(store.disruptions.values())
    if stage is not None:
        items = [d for d in items if d.stage == stage]
    items = items[:limit]
    summaries = [
        DisruptionSummary(
            id=d.id, type=d.type, stage=d.stage, detected_at=d.detected_at, vendor=d.vendor,
            headline=d.headline, exposure_total_paise=d.exposure.total_paise,
            exposure_total_display=d.exposure.total_display, detector_source=d.detector_source,
        )
        for d in items
    ]
    return DisruptionList(items=summaries, total=len(summaries))


@router.get("", response_model=DisruptionList)
def list_disruptions(
    stage: DisruptionStage | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DisruptionList:
    if settings.use_mocks:
        return _list_disruptions_mock(stage, limit)
    return repo.list_disruptions(session, stage.value if stage else None, limit)


@router.get("/{disruption_id}", response_model=Disruption)
def get_disruption(disruption_id: str, session: Session = Depends(get_session)) -> Disruption:
    if settings.use_mocks:
        d = store.disruptions.get(disruption_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Disruption not found")
        return d

    d = repo.get_disruption(session, disruption_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Disruption not found")
    return d


@router.get("/{disruption_id}/impact", response_model=ImpactGraph)
def get_disruption_impact(disruption_id: str, session: Session = Depends(get_session)) -> ImpactGraph:
    if settings.use_mocks:
        graph = store.impact_graphs.get(disruption_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Disruption not found")
        return graph

    disruption = repo.get_disruption_row(session, disruption_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Disruption not found")
    return get_or_build_impact_graph(session, disruption)


@router.get("/{disruption_id}/plan", response_model=PlanDiffResponse)
def get_disruption_plan(disruption_id: str, session: Session = Depends(get_session)) -> PlanDiffResponse:
    """Latest remediation plan, shaped as the two-sided diff the frontend's
    PlanDiffPanel renders: incumbent PO lines on the left, the solver's
    proposed allocation on the right."""
    from app.db.models import PurchaseOrder, Vendor
    from app.schemas.money import format_inr, to_iso
    from app.schemas.planner import PlanChangeDetail, PlanRowItem

    plan_row = session.query(RemediationPlanRow).filter_by(disruption_id=disruption_id).order_by(RemediationPlanRow.created_at.desc()).first()
    if plan_row is None:
        raise HTTPException(status_code=404, detail="No plan found for this disruption")

    disruption = repo.get_disruption_row(session, disruption_id)
    incumbent = session.get(Vendor, disruption.vendor_id) if disruption else None
    pos = (
        session.query(PurchaseOrder).filter(PurchaseOrder.id.in_(disruption.affected_po_ids or [])).all()
        if disruption
        else []
    )
    current_rows = [
        PlanRowItem(
            vendor_id=po.vendor_id,
            vendor_name=incumbent.name if incumbent else "Incumbent vendor",
            item=po.item_name,
            qty=po.qty,
            unit_price_paise=po.unit_price_paise,
            unit_price_display=format_inr(po.unit_price_paise),
            lead_time_days=max((po.promised_at - po.ordered_at).days, 0),
            eta=to_iso(po.promised_at)[:10],
        )
        for po in pos
        if po.delivered_at is None
    ]

    vendor_rows: list[PlanRowItem] = []
    internal_rows: list[PlanRowItem] = []
    for change in plan_row.changes:
        row = PlanRowItem(
            vendor_id=change.get("vendor_id") or "internal",
            vendor_name=change.get("vendor_name") or "Internal stock",
            item=change.get("item_name") or change.get("item_sku") or "",
            qty=change.get("qty", 0),
            unit_price_paise=change.get("unit_price_paise", 0),
            unit_price_display=change.get("unit_price_display", "₹0"),
            lead_time_days=change.get("lead_time_days", 0),
            eta=change.get("eta_date", ""),
        )
        if change.get("kind") == "PULL_FORWARD_STOCK":
            internal_rows.append(row)
        else:
            vendor_rows.append(row)

    changes: list[PlanChangeDetail] = []
    if vendor_rows:
        split = len(vendor_rows) + len(internal_rows) > 1
        changes.append(
            PlanChangeDetail(
                id=f"{plan_row.id}-supply",
                kind="SPLIT_ORDER" if split else "SWITCH_VENDOR",
                description=(
                    f"Order split across {len(vendor_rows)} vendor(s)"
                    + (" + internal stock" if internal_rows else "")
                    if split
                    else f"Switch to {vendor_rows[0].vendor_name}"
                ),
                rationale=next((c.get("rationale") for c in plan_row.changes if c.get("rationale")), "")
                or "Solver-optimal allocation across verified backup vendors, minimizing cost plus lateness penalty.",
                current=current_rows,
                proposed=vendor_rows,
            )
        )
    for row in internal_rows:
        changes.append(
            PlanChangeDetail(
                id=f"{plan_row.id}-internal",
                kind="PULL_FORWARD_STOCK",
                description=f"Pull {row.qty:,} units from internal stock",
                rationale="Existing inventory above safety stock covers part of the shortfall at zero purchase cost.",
                current=[],
                proposed=[row],
            )
        )

    return PlanDiffResponse(
        id=plan_row.id,
        disruption_id=plan_row.disruption_id,
        changes=changes,
        exposure_before_paise=plan_row.before_exposure_paise,
        exposure_before_display=format_inr(plan_row.before_exposure_paise),
        exposure_after_paise=plan_row.after_exposure_paise,
        exposure_after_display=format_inr(plan_row.after_exposure_paise),
        cost_to_resolve_paise=plan_row.cost_to_resolve_paise,
        cost_to_resolve_display=format_inr(plan_row.cost_to_resolve_paise),
        net_saving_paise=plan_row.net_saving_paise,
        net_saving_display=format_inr(plan_row.net_saving_paise),
        requires_escalation=plan_row.requires_escalation,
        escalation_reason=plan_row.escalation_reason,
        solver="OR_TOOLS_CP_SAT" if plan_row.solver == "ORTOOLS_CPSAT" else "GREEDY_FALLBACK",
        solve_ms=plan_row.solve_ms,
    )
