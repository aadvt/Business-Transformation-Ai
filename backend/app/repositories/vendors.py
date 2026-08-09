"""Vendor queries. Backs GET /vendors, /vendors/{id}, /vendors/dues,
/vendors/{id}/context — same response shapes as Phase 1's mock store.

`dues` isn't a stored vendor column (see CLAUDE.md table list) — it's derived
live from PENDING settlement_items. `guardrails`/`briefing`/`history_summary`
in vendor context aren't modeled tables either; they're computed from the
vendor row + its purchase order and comm event history at query time.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CommEvent, PurchaseOrder, SettlementItem, Vendor as VendorRow
from app.schemas.enums import MemorySource
from app.schemas.money import format_inr, to_iso
from app.schemas.vendors import (
    Guardrails,
    LastTerms,
    Reliability,
    Vendor,
    VendorContext,
    VendorContextVendor,
    VendorDue,
    VendorDuesResponse,
    VendorList,
    VendorRef,
)


def _vendor_dues_paise(session: Session, vendor_id: str) -> int:
    total = session.execute(
        select(func.coalesce(func.sum(SettlementItem.amount_paise), 0)).where(
            SettlementItem.vendor_id == vendor_id, SettlementItem.status == "PENDING"
        )
    ).scalar_one()
    return int(total)


def _to_vendor_schema(session: Session, row: VendorRow) -> Vendor:
    dues = _vendor_dues_paise(session, row.id)
    return Vendor(
        id=row.id,
        created_at=to_iso(row.created_at),
        updated_at=to_iso(row.updated_at),
        name=row.name,
        category=row.category,
        gstin=row.gstin,
        udyam_number=row.udyam_number,
        phone=row.phone,
        languages=row.languages or [],
        city=row.city,
        state=row.state,
        lat=row.lat,
        lng=row.lng,
        reliability_score_0_100=row.reliability_score,
        on_time_rate=row.on_time_rate,
        orders_completed=row.orders_completed,
        disputes=row.disputes,
        dues_paise=dues,
        dues_display=format_inr(dues),
    )


def list_vendors(session: Session, search: str | None, limit: int) -> VendorList:
    query = select(VendorRow)
    if search:
        needle = f"%{search.lower()}%"
        query = query.where(
            func.lower(VendorRow.name).like(needle)
            | func.lower(VendorRow.category).like(needle)
            | func.lower(VendorRow.city).like(needle)
        )
    rows = session.execute(query.order_by(VendorRow.name).limit(limit)).scalars().all()
    items = [_to_vendor_schema(session, r) for r in rows]
    return VendorList(items=items, total=len(items))


def get_vendor(session: Session, vendor_id: str) -> Vendor | None:
    row = session.get(VendorRow, vendor_id)
    if row is None:
        return None
    return _to_vendor_schema(session, row)


def get_vendor_dues(session: Session) -> VendorDuesResponse:
    rows = session.execute(
        select(
            SettlementItem.vendor_id,
            func.sum(SettlementItem.amount_paise),
            func.count(SettlementItem.id),
            func.min(SettlementItem.due_date),
        )
        .where(SettlementItem.status == "PENDING")
        .group_by(SettlementItem.vendor_id)
    ).all()

    items: list[VendorDue] = []
    total = 0
    today = date.today()
    for vendor_id, amount, count, oldest_due in rows:
        vendor = session.get(VendorRow, vendor_id)
        if vendor is None:
            continue
        amount = int(amount)
        total += amount
        age_days = max(0, (today - oldest_due).days) if oldest_due else 0
        items.append(
            VendorDue(
                vendor=VendorRef(id=vendor.id, name=vendor.name, gstin=vendor.gstin),
                total_due_paise=amount,
                total_due_display=format_inr(amount),
                oldest_invoice_age_days=age_days,
                invoice_count=int(count),
            )
        )

    return VendorDuesResponse(items=items, total_due_paise=total, total_due_display=format_inr(total))


_HISTORY_SUMMARY_MAX = 400
_BRIEFING_MAX = 300


def get_vendor_context(session: Session, vendor_id: str) -> VendorContext | None:
    vendor = session.get(VendorRow, vendor_id)
    if vendor is None:
        return None

    last_po = session.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.vendor_id == vendor_id, PurchaseOrder.delivered_at.is_not(None))
        .order_by(PurchaseOrder.delivered_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    last_terms = None
    if last_po is not None:
        last_terms = LastTerms(
            unit_price_paise=last_po.unit_price_paise,
            lead_time_days=max(0, (last_po.promised_at - last_po.ordered_at).days),
            payment_terms_days=vendor.payment_terms_days,
            agreed_at=to_iso(last_po.delivered_at),
        )

    open_dispute = session.execute(
        select(func.count()).select_from(PurchaseOrder).where(
            PurchaseOrder.vendor_id == vendor_id, PurchaseOrder.status == "QUALITY_REJECTED"
        )
    ).scalar_one()

    history_summary = (
        f"{vendor.category} vendor in {vendor.city}, {vendor.orders_completed} orders completed at a "
        f"{round(vendor.on_time_rate * 100)}% on-time rate"
        + (f", with {open_dispute} quality dispute(s) on record" if open_dispute else "")
        + "."
    )[:_HISTORY_SUMMARY_MAX]

    if vendor.reliability_score >= 80:
        briefing = f"{vendor.name} is a reliable {vendor.category.lower()} vendor — routine call, no known open issues."
    elif open_dispute:
        briefing = f"{vendor.name} has an open quality dispute on record — confirm they are aware before discussing new orders."
    else:
        briefing = f"{vendor.name} has a mixed reliability record — confirm current terms before committing to new volume."
    briefing = briefing[:_BRIEFING_MAX]

    guardrails = Guardrails(
        max_unit_price_paise=int((last_po.unit_price_paise if last_po else 5000) * 1.15),
        max_lead_time_days=max(3, round(vendor.avg_lead_time_days) + 2),
        requires_human_above_paise=50_000_000,
    )

    comm_count = session.execute(
        select(func.count()).select_from(CommEvent).where(CommEvent.vendor_id == vendor_id)
    ).scalar_one()
    memory_source = MemorySource.SUPERMEMORY if comm_count > 0 else MemorySource.DB_ONLY

    return VendorContext(
        vendor=VendorContextVendor(
            id=vendor.id, name=vendor.name, category=vendor.category, gstin=vendor.gstin,
            phone=vendor.phone, languages=vendor.languages or [],
        ),
        reliability=Reliability(
            score_0_100=vendor.reliability_score, on_time_rate=vendor.on_time_rate,
            orders_completed=vendor.orders_completed, disputes=vendor.disputes,
        ),
        last_terms=last_terms,
        history_summary=history_summary,
        briefing=briefing,
        guardrails=guardrails,
        memory_source=memory_source,
    )
