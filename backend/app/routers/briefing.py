from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import DEFAULT_ORG_ID
from app.db.models import InventorySnapshot, Vendor
from app.db.session import get_session
from app.schemas.money import utc_now
from app.agents.detectors.ttm_forecast import fetch_history, run_forecast, SKU_VENDOR_HINTS

router = APIRouter(prefix="/api/v1/briefing", tags=["briefing"])

@router.get("")
def get_briefing(session: Session = Depends(get_session)):
    items = []
    skus = session.execute(select(InventorySnapshot.sku).where(InventorySnapshot.org_id == DEFAULT_ORG_ID).distinct()).scalars().all()
    for sku in skus:
        result = run_forecast(sku, fetch_history(session, DEFAULT_ORG_ID, sku))
        if result is None or result.projected_breach_at is None: continue
        vendor = session.execute(select(Vendor).where(Vendor.name == SKU_VENDOR_HINTS.get(sku))).scalar_one_or_none()
        days = max(0, (result.projected_breach_at - utc_now()).days)
        items.append({"title": f"{sku} may breach reorder point", "detail": f"Forecast crosses the reorder point in {days} days.", "item_sku": sku, "days_of_cover": days, "vendor_lead_time_days": round(vendor.avg_lead_time_days) if vendor else None, "order_by_date": (result.projected_breach_at - timedelta(days=round(vendor.avg_lead_time_days) if vendor else 0)).date().isoformat(), "severity": "HIGH" if days <= 7 else "MEDIUM"})
    return {"next_7_days": [item for item in items if item["days_of_cover"] <= 7], "watchlist": [item for item in items if item["days_of_cover"] > 7], "all_clear": not items}
