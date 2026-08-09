from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db_models import Negotiation as NegotiationRow
from app.db_models import SettlementItem
from app.db_models import Vendor as VendorRow
from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.enums import MemorySource
from app.schemas.money import format_inr
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

router = APIRouter(prefix="/api/v1/vendors", tags=["vendors"], dependencies=[Depends(require_api_key)])

# The vendors table has no lat/lng columns — the frontend's Network map
# needs coordinates, so these are city-center approximations for the exact
# 6 cities the 24 real vendor rows are in (confirmed via a distinct-city
# query against the live DB, not guessed).
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "Chennai": (13.0827, 80.2707),
    "Coimbatore": (11.0168, 76.9558),
    "Jaipur": (26.9124, 75.7873),
    "Ludhiana": (30.9010, 75.8573),
    "Pune": (18.5204, 73.8567),
    "Rajkot": (22.3039, 70.8022),
}


async def _dues_by_vendor(db: AsyncSession) -> dict[str, tuple[int, int, date | None]]:
    """vendor_id -> (total_due_paise, invoice_count, oldest_due_date) for
    not-yet-confirmed settlement_items. There's no dues_paise column on
    vendors — this is the real source: amounts owed, tracked with status
    and due date."""
    stmt = (
        select(
            SettlementItem.vendor_id,
            func.sum(SettlementItem.amount_paise),
            func.count(SettlementItem.id),
            func.min(SettlementItem.due_date),
        )
        .where(SettlementItem.status != "CONFIRMED")
        .group_by(SettlementItem.vendor_id)
    )
    result = await db.execute(stmt)
    return {
        vendor_id: (int(total), int(count), oldest_due)
        for vendor_id, total, count, oldest_due in result.all()
    }


def _to_vendor(row: VendorRow, dues_paise: int) -> Vendor:
    lat, lng = _CITY_COORDS.get(row.city, (0.0, 0.0))
    return Vendor(
        id=row.id,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
        name=row.name,
        category=row.category,
        gstin=row.gstin,
        udyam_number=row.udyam_number,
        phone=row.phone,
        email=row.email,
        languages=row.languages or [],
        city=row.city,
        state=row.state,
        lat=lat,
        lng=lng,
        reliability_score_0_100=row.reliability_score,
        on_time_rate=row.on_time_rate,
        orders_completed=row.orders_completed,
        disputes=row.disputes,
        avg_lead_time_days=row.avg_lead_time_days,
        is_backup_pool=row.is_backup_pool,
        payment_terms_days=row.payment_terms_days,
        dues_paise=dues_paise,
        dues_display=format_inr(dues_paise),
    )


@router.get("", response_model=VendorList)
async def list_vendors(
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> VendorList:
    stmt = select(VendorRow).where(VendorRow.org_id == settings.org_id)
    if search:
        needle = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(VendorRow.name).like(needle)
            | func.lower(VendorRow.category).like(needle)
            | func.lower(VendorRow.city).like(needle)
        )
    stmt = stmt.limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    dues = await _dues_by_vendor(db)
    items = [_to_vendor(v, dues.get(v.id, (0, 0, None))[0]) for v in rows]
    return VendorList(items=items, total=len(items))


@router.get("/dues", response_model=VendorDuesResponse)
async def get_vendor_dues(db: AsyncSession = Depends(get_db)) -> VendorDuesResponse:
    dues = await _dues_by_vendor(db)
    if not dues:
        return VendorDuesResponse(items=[], total_due_paise=0, total_due_display=format_inr(0))

    vendor_rows = (
        (await db.execute(select(VendorRow).where(VendorRow.id.in_(dues.keys())))).scalars().all()
    )
    vendors_by_id = {v.id: v for v in vendor_rows}

    today = date.today()
    items = [
        VendorDue(
            vendor=VendorRef(id=v.id, name=v.name, gstin=v.gstin),
            total_due_paise=total_paise,
            total_due_display=format_inr(total_paise),
            oldest_invoice_age_days=(today - oldest_due).days if oldest_due else 0,
            invoice_count=count,
        )
        for vendor_id, (total_paise, count, oldest_due) in dues.items()
        if (v := vendors_by_id.get(vendor_id)) is not None
    ]
    total = sum(i.total_due_paise for i in items)
    return VendorDuesResponse(items=items, total_due_paise=total, total_due_display=format_inr(total))


@router.get("/{vendor_id}", response_model=Vendor)
async def get_vendor(vendor_id: str, db: AsyncSession = Depends(get_db)) -> Vendor:
    row = await db.get(VendorRow, vendor_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    dues = await _dues_by_vendor(db)
    return _to_vendor(row, dues.get(vendor_id, (0, 0, None))[0])


@router.get("/{vendor_id}/context", response_model=VendorContext)
async def get_vendor_context(vendor_id: str, db: AsyncSession = Depends(get_db)) -> VendorContext:
    v = await db.get(VendorRow, vendor_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Hybrid, deliberately: identity/reliability/last-terms are real (DB);
    # guardrails/briefing/history_summary need either real business-policy
    # config or LLM-generated narrative, neither of which exists as stored
    # data yet, so they stay fixture-backed for the vendors that have an
    # entry. See CONTRACT.md.
    ctx = store.vendor_context_raw.get(vendor_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Vendor context not available")

    last_negotiation = (
        await db.execute(
            select(NegotiationRow)
            .where(NegotiationRow.vendor_id == vendor_id, NegotiationRow.agreed_unit_price_paise.is_not(None))
            .order_by(NegotiationRow.ended_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    last_terms = None
    if last_negotiation is not None:
        last_terms = LastTerms(
            unit_price_paise=last_negotiation.agreed_unit_price_paise,
            lead_time_days=last_negotiation.agreed_lead_time_days or 0,
            payment_terms_days=last_negotiation.agreed_payment_terms_days or 0,
            agreed_at=(last_negotiation.ended_at or last_negotiation.started_at).isoformat(),
        )
    elif ctx.get("last_terms"):
        last_terms = LastTerms.model_validate(ctx["last_terms"])

    return VendorContext(
        vendor=VendorContextVendor(
            id=v.id, name=v.name, category=v.category, gstin=v.gstin, phone=v.phone, languages=v.languages or []
        ),
        reliability=Reliability(
            score_0_100=v.reliability_score,
            on_time_rate=v.on_time_rate,
            orders_completed=v.orders_completed,
            disputes=v.disputes,
        ),
        last_terms=last_terms,
        history_summary=ctx["history_summary"],
        briefing=ctx["briefing"],
        guardrails=Guardrails.model_validate(ctx["guardrails"]),
        memory_source=MemorySource(ctx["memory_source"]),
    )
