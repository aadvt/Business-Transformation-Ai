from datetime import datetime
import uuid
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.constants import DEFAULT_ORG_ID
from app.db.models import BusinessProfile, InventorySnapshot, PurchaseOrder, Vendor
from app.db.session import get_session
from app.schemas.money import to_iso, utc_now

router = APIRouter(prefix="/api/v1/business", tags=["business"])
QUESTIONS = [
    {"id": "critical_vendors", "question": "Which vendors would hurt most if unavailable?", "options": ["Top spend", "Single-source", "Longest lead time"]},
    {"id": "payment_cycle_days", "question": "What is your usual payment cycle?", "options": ["15 days", "30 days", "45 days", "60 days"]},
    {"id": "peak_months", "question": "Which months are your peak season?", "options": ["Jan-Mar", "Apr-Jun", "Jul-Sep", "Oct-Dec"]},
    {"id": "single_source_items", "question": "Which items have only one source?", "options": ["Fasteners", "Castings", "Packaging", "None"]},
]

class Answers(BaseModel): answers: dict

def _profile(session: Session, answers: dict | None = None):
    vendors = session.execute(select(Vendor).where(Vendor.org_id == DEFAULT_ORG_ID)).scalars().all()
    pos = session.execute(select(PurchaseOrder).where(PurchaseOrder.org_id == DEFAULT_ORG_ID)).scalars().all()
    current = session.execute(select(BusinessProfile).where(BusinessProfile.org_id == DEFAULT_ORG_ID)).scalar_one_or_none()
    if current is None: current = BusinessProfile(id=str(uuid.uuid4()), org_id=DEFAULT_ORG_ID, updated_at=utc_now()); session.add(current)
    current.vendor_count = len(vendors); current.item_count = len({po.item_sku for po in pos}); current.categories = sorted({v.category for v in vendors}); current.avg_payment_cycle_days = round(sum(v.payment_terms_days for v in vendors) / len(vendors), 1) if vendors else 0; current.plant_locations = []; current.top_dependencies = []; current.answers = answers if answers is not None else (current.answers or {}); current.updated_at = utc_now(); session.flush(); return current

@router.get("/questions")
def questions(): return {"questions": QUESTIONS}

@router.get("/profile")
def profile(session: Session = Depends(get_session)):
    row = _profile(session); return {"vendor_count": row.vendor_count, "item_count": row.item_count, "categories": row.categories, "avg_payment_cycle_days": row.avg_payment_cycle_days, "peak_months": row.peak_months, "plant_locations": row.plant_locations, "top_dependencies": row.top_dependencies, "answers": row.answers, "updated_at": to_iso(row.updated_at)}

@router.post("/answers")
def answers(body: Answers, session: Session = Depends(get_session)):
    row = _profile(session, body.answers); session.commit(); return {"status": "saved", "updated_at": to_iso(row.updated_at)}
