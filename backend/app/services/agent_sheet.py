"""D5a context delivery for the manually operated Bolna voice agent."""
import csv
import io
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import AgentSheetSync, DisruptionEvent, Negotiation, PurchaseOrder, Vendor, VendorCandidate
from app.repositories.vendors import get_vendor_context
from app.schemas.money import format_inr, to_iso, utc_now

logger = logging.getLogger("sanjeevani.agent_sheet")
HEADERS = ["vendor_id", "vendor_name", "phone", "language", "category", "item_name", "required_qty", "target_unit_price", "max_unit_price", "max_lead_time_days", "last_agreed_price", "reliability", "briefing", "updated_at"]

@dataclass
class AgentRow:
    vendor_id: str; vendor_name: str; phone: str; language: str; category: str; item_name: str
    required_qty: int; target_unit_price: str; max_unit_price: str; max_lead_time_days: int
    last_agreed_price: str; reliability: str; briefing: str; updated_at: str

def _norm_phone(value: str | None) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("91") and len(digits) > 10: digits = digits[2:]
    if digits.startswith("0") and len(digits) > 10: digits = digits[1:]
    return digits[-10:]

def _row(session: Session, vendor: Vendor, *, item_name: str, required_qty: int, target: int, lead: int) -> AgentRow:
    ctx = get_vendor_context(session, vendor.id)
    guard = ctx.guardrails
    last = ctx.last_terms
    # The agent speaks these values, so this is the one deliberate rupee-string boundary.
    return AgentRow(vendor.id, vendor.name, vendor.phone, (vendor.languages or ["en"])[0], vendor.category,
        item_name, required_qty, format_inr(target), format_inr(guard.max_unit_price_paise), guard.max_lead_time_days,
        format_inr(last.unit_price_paise) if last else "first order",
        f"{vendor.orders_completed - vendor.disputes} of {vendor.orders_completed} on time" if vendor.orders_completed else "no prior orders",
        ctx.briefing.replace("\n", " ")[:300], to_iso(vendor.updated_at))

def build_agent_rows(session: Session, org_id: str, disruption_id: str | None = None) -> list[AgentRow]:
    if disruption_id:
        disruption = session.get(DisruptionEvent, disruption_id)
        if not disruption: return []
        pos = session.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(disruption.affected_po_ids or []))).scalars().all()
        item = pos[0].item_name if pos else "urgent replacement supply"
        qty = sum(p.qty for p in pos)
        target = int(pos[0].unit_price_paise) if pos else 0
        candidates = session.execute(select(VendorCandidate, Vendor).join(Vendor, Vendor.id == VendorCandidate.vendor_id).where(VendorCandidate.disruption_id == disruption_id).order_by(VendorCandidate.rank)).all()
        return [_row(session, v, item_name=item, required_qty=qty, target=int(c.quoted_unit_price_paise), lead=c.quoted_lead_time_days) for c, v in candidates]
    vendors = session.execute(select(Vendor).where(Vendor.org_id == org_id, Vendor.is_backup_pool.is_(True)).order_by(Vendor.name)).scalars().all()
    return [_row(session, v, item_name="backup pool", required_qty=0, target=0, lead=0) for v in vendors]

def rows_csv(rows: list[AgentRow]) -> str:
    out = io.StringIO(); writer = csv.writer(out); writer.writerow(HEADERS)
    for row in rows: writer.writerow([getattr(row, h) for h in HEADERS])
    return out.getvalue()

def resolve_vendor(session: Session, extracted: dict | None, phone: str | None):
    extracted = extracted or {}
    vendor_id = extracted.get("vendor_id")
    if vendor_id:
        vendor = session.get(Vendor, str(vendor_id))
        if vendor: return vendor, "vendor_id"
    normalized = _norm_phone(phone or extracted.get("phone") or extracted.get("callee_phone"))
    if normalized:
        for vendor in session.execute(select(Vendor)).scalars():
            if _norm_phone(vendor.phone) == normalized: return vendor, "phone"
    pending = session.execute(select(Negotiation).where(Negotiation.status.in_(["PENDING", "IN_PROGRESS", "NEGOTIATING"])).order_by(Negotiation.started_at.desc())).scalars().first()
    if pending:
        vendor = session.get(Vendor, pending.vendor_id)
        if vendor: return vendor, "pending_session"
    return None, "none"

def sync_sheet(session: Session, org_id: str, disruption_id: str | None = None) -> dict:
    rows = build_agent_rows(session, org_id, disruption_id)
    now = utc_now()
    result = {"status": "UNAVAILABLE", "rows_written": 0, "worksheet": settings.google_sheets_worksheet_name, "synced_at": to_iso(now)}
    try:
        if not settings.google_service_account_json or not settings.google_sheets_spreadsheet_id:
            raise RuntimeError("Google Sheets credentials are not configured")
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(settings.google_service_account_json, scopes=scopes)
        sheet = gspread.authorize(creds).open_by_key(settings.google_sheets_spreadsheet_id).worksheet(settings.google_sheets_worksheet_name)
        values = [HEADERS] + [[getattr(row, h) for h in HEADERS] for row in rows]
        sheet.clear(); sheet.update(values, "A1")
        result.update(status="SYNCED", rows_written=len(rows))
    except Exception as exc:
        result["reason"] = str(exc)[:500]; logger.warning("agent_sheet_sync_unavailable", extra={"reason": str(exc)[:200]})
    session.add(AgentSheetSync(id=os.urandom(16).hex(), org_id=org_id, disruption_id=disruption_id, status=result["status"], rows_written=result["rows_written"], synced_at=now, reason=result.get("reason")))
    session.commit()
    return result
