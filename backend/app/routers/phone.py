"""Phone mock — message thread derived from existing data.

Honest deliverable: WhatsApp Business API integration is NOT implemented.
The mock UI thread is what reaches users. This endpoint derives the
conversation from DB state — disruptions, exposure, plans, approvals,
negotiations, settlements — deterministically, in the exact shape the
frontend's /phone page renders:

  { items: [{ id, kind: TEXT|APPROVAL_CARD|SYSTEM, from: AGENT|OWNER, text,
              at, approval_id?, disruption_id?, headline?, exposure_display?,
              plan_summary?, status? }] }

Message ids are deterministic (derived from the source row's id), so the
frontend's seen-set dedupe works across refetches.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.db.models import (
    Approval as ApprovalRow,
    DisruptionEvent,
    ExposureCalc,
    Negotiation,
    RemediationPlanRow,
    SettlementBatchRow,
    Vendor,
)
from app.deps import require_api_key
from app.schemas.money import format_inr, to_iso

router = APIRouter(prefix="/api/v1/phone", tags=["phone"], dependencies=[Depends(require_api_key)])

_STATUS_MAP = {"PENDING": "PENDING", "APPROVED": "APPROVED", "REJECTED": "REJECTED", "OPTIONS_REQUESTED": "OPTIONS_REQUESTED"}


def _latest_by_disruption(session: Session, model, disruption_ids: list[str], order_col) -> dict:
    """Newest row of `model` per disruption, in one query. This endpoint is
    polled every 5s by the phone UI, so a per-disruption round-trip to Neon is
    latency the demo pays over and over."""
    if not disruption_ids:
        return {}
    rows = session.execute(
        select(model).where(model.disruption_id.in_(disruption_ids)).order_by(order_col.asc())
    ).scalars().all()
    return {row.disruption_id: row for row in rows}  # ascending: last write wins


def _plan_summary(plan: RemediationPlanRow | None) -> list[str]:
    if plan is None:
        return ["Source from verified backup vendors", "Expedite replacement delivery"]
    lines = []
    for change in plan.changes:
        if change.get("kind") == "PULL_FORWARD_STOCK":
            lines.append(f"Pull {change.get('qty', 0):,} units from internal stock")
        else:
            lines.append(
                f"{change.get('qty', 0):,} units from {change.get('vendor_name', 'backup vendor')} at {change.get('unit_price_display', '')}"
            )
    lines.append(f"Cost to resolve {format_inr(plan.cost_to_resolve_paise)} · saves {format_inr(plan.net_saving_paise)}")
    return lines[:4]


@router.get("/messages")
def get_phone_messages(
    disruption_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    items: list[dict] = []

    query = select(DisruptionEvent).order_by(DisruptionEvent.detected_at.asc())
    if disruption_id:
        query = query.where(DisruptionEvent.id == disruption_id)
    else:
        # The demo thread: every disruption that progressed far enough to have
        # an approval, newest few only so the thread stays readable.
        query = query.where(DisruptionEvent.stage.notin_(["DETECTED"])).limit(6)
    disruptions = session.execute(query).scalars().all()

    # Batch every per-disruption lookup up front (see _latest_by_disruption).
    d_ids = [d.id for d in disruptions]
    exposure_by_d = _latest_by_disruption(session, ExposureCalc, d_ids, ExposureCalc.computed_at)
    approval_by_d = _latest_by_disruption(session, ApprovalRow, d_ids, ApprovalRow.requested_at)
    plan_by_d = _latest_by_disruption(session, RemediationPlanRow, d_ids, RemediationPlanRow.created_at)
    negotiation_by_d = _latest_by_disruption(session, Negotiation, d_ids, Negotiation.started_at)
    vendor_ids = {d.vendor_id for d in disruptions} | {n.vendor_id for n in negotiation_by_d.values()}
    vendors_by_id = {
        v.id: v for v in session.execute(select(Vendor).where(Vendor.id.in_(vendor_ids))).scalars().all()
    } if vendor_ids else {}

    for d in disruptions:
        vendor = vendors_by_id.get(d.vendor_id)
        calc = exposure_by_d.get(d.id)
        exposure_display = format_inr(calc.total_paise if calc else 0)

        items.append({
            "id": f"alert-{d.id}",
            "kind": "TEXT",
            "from": "AGENT",
            "text": f"⚠️ Supply disruption: {d.headline}\nEstimated exposure {exposure_display}.",
            "at": to_iso(d.detected_at),
            "disruption_id": d.id,
        })

        approval = approval_by_d.get(d.id)
        if approval:
            items.append({
                "id": f"card-{approval.id}",
                "kind": "APPROVAL_CARD",
                "from": "AGENT",
                "text": None,
                "at": to_iso(approval.requested_at),
                "approval_id": approval.id,
                "disruption_id": d.id,
                "headline": d.headline,
                "exposure_display": exposure_display,
                "plan_summary": _plan_summary(plan_by_d.get(d.id)),
                "status": _STATUS_MAP.get(approval.status, approval.status),
            })
            if approval.decided_at:
                approved = approval.status == "APPROVED"
                items.append({
                    "id": f"decision-{approval.id}",
                    "kind": "TEXT",
                    "from": "OWNER",
                    "text": "Approved. Go ahead." if approved else "Show me other options.",
                    "at": to_iso(approval.decided_at),
                    "disruption_id": d.id,
                })

        negotiation = negotiation_by_d.get(d.id)
        if negotiation and negotiation.status == "AGREED" and negotiation.ended_at:
            price = (
                f" at {format_inr(negotiation.agreed_unit_price_paise)}/unit"
                if negotiation.agreed_unit_price_paise
                else ""
            )
            backup = vendors_by_id.get(negotiation.vendor_id)
            items.append({
                "id": f"negotiated-{negotiation.id}",
                "kind": "TEXT",
                "from": "AGENT",
                "text": f"✅ Deal closed with {backup.name if backup else 'backup vendor'}{price}. "
                        f"{'Original vendor: ' + vendor.name + '. ' if vendor else ''}Purchase order sent.",
                "at": to_iso(negotiation.ended_at),
                "disruption_id": d.id,
            })

    batches = session.execute(
        select(SettlementBatchRow)
        .where(SettlementBatchRow.org_id == DEFAULT_ORG_ID)
        .order_by(SettlementBatchRow.staged_at.desc())
        .limit(2)
    ).scalars().all()
    for batch in batches:
        items.append({
            "id": f"settlement-{batch.id}",
            "kind": "SYSTEM",
            "from": "AGENT",
            "text": f"Settlement batch {batch.period_month}: {batch.item_count} invoices, {format_inr(batch.total_paise)} staged for payout.",
            "at": to_iso(batch.staged_at),
        })

    items.sort(key=lambda m: m["at"])
    return {"items": items}
