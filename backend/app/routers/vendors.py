from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.enums import MemorySource
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


@router.get("", response_model=VendorList)
def list_vendors(
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> VendorList:
    items = list(store.vendors.values())
    if search:
        needle = search.lower()
        items = [
            v
            for v in items
            if needle in v.name.lower() or needle in v.category.lower() or needle in v.city.lower()
        ]
    items = items[:limit]
    return VendorList(items=items, total=len(items))


@router.get("/dues", response_model=VendorDuesResponse)
def get_vendor_dues() -> VendorDuesResponse:
    from app.schemas.money import format_inr

    items = [
        VendorDue(
            vendor=VendorRef(id=v.id, name=v.name, gstin=v.gstin),
            total_due_paise=v.dues_paise,
            total_due_display=v.dues_display,
            oldest_invoice_age_days=30,
            invoice_count=1,
        )
        for v in store.vendors.values()
        if v.dues_paise > 0
    ]
    total = sum(i.total_due_paise for i in items)
    return VendorDuesResponse(items=items, total_due_paise=total, total_due_display=format_inr(total))


@router.get("/{vendor_id}", response_model=Vendor)
def get_vendor(vendor_id: str) -> Vendor:
    v = store.vendors.get(vendor_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return v


@router.get("/{vendor_id}/context", response_model=VendorContext)
def get_vendor_context(vendor_id: str) -> VendorContext:
    v = store.vendors.get(vendor_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Vendor not found")
    ctx = store.vendor_context_raw.get(vendor_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Vendor context not available")
    return VendorContext(
        vendor=VendorContextVendor(
            id=v.id, name=v.name, category=v.category, gstin=v.gstin, phone=v.phone, languages=v.languages
        ),
        reliability=Reliability(
            score_0_100=v.reliability_score_0_100,
            on_time_rate=v.on_time_rate,
            orders_completed=v.orders_completed,
            disputes=v.disputes,
        ),
        last_terms=LastTerms.model_validate(ctx["last_terms"]) if ctx["last_terms"] else None,
        history_summary=ctx["history_summary"],
        briefing=ctx["briefing"],
        guardrails=Guardrails.model_validate(ctx["guardrails"]),
        memory_source=MemorySource(ctx["memory_source"]),
    )
