import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import CallSession, DisruptionEvent, Vendor
from app.db.session import SessionLocal
from app.schemas.calls import CallSessionResponse, CallStartRequest
from app.services.agent_sheet import build_agent_rows, resolve_vendor
from app.services.bolna import parse_bolna_payload, validate_extracted
from app.schemas.money import to_iso, utc_now

logger = logging.getLogger("sanjeevani.webhooks")
router = APIRouter(prefix="/api/v1", tags=["calls"])

def _response(row: CallSession) -> CallSessionResponse:
    return CallSessionResponse(id=row.id, disruption_id=row.disruption_id, vendor_id=row.vendor_id, status=row.status, source=row.source, started_at=to_iso(row.started_at), ended_at=to_iso(row.ended_at) if row.ended_at else None, language=row.language, phone=row.phone, briefing_snapshot=row.briefing_snapshot or {}, guardrails=row.guardrails or {}, transcript=row.transcript or [], extracted=row.extracted or {}, validation=row.validation or {}, correlation_method=row.correlation_method, outcome_status=row.outcome_status)

@router.post("/calls/start", response_model=CallSessionResponse)
def start_call(body: CallStartRequest):
    with SessionLocal() as session:
        vendor = session.get(Vendor, body.vendor_id)
        disruption = session.get(DisruptionEvent, body.disruption_id)
        if not vendor or not disruption: raise HTTPException(status_code=404, detail="Vendor or disruption not found")
        rows = [r for r in build_agent_rows(session, DEFAULT_ORG_ID, body.disruption_id) if r.vendor_id == vendor.id]
        if not rows: raise HTTPException(status_code=404, detail="Vendor is not a sourcing candidate")
        row = rows[0]
        snapshot = asdict(row)
        guardrails = {"max_unit_price": row.max_unit_price, "max_lead_time_days": row.max_lead_time_days}
        now = utc_now()
        call = CallSession(id=str(uuid.uuid4()), disruption_id=body.disruption_id, vendor_id=vendor.id, status="DIALING", source="REPLAY" if body.mode == "REPLAY" else "LIVE_BOLNA", started_at=now, language=row.language, phone=vendor.phone, briefing_snapshot=snapshot, guardrails=guardrails)
        session.add(call); session.flush(); session.commit()
        return _response(call)

@router.get("/calls/{call_id}", response_model=CallSessionResponse)
def get_call(call_id: str):
    with SessionLocal() as session:
        row = session.get(CallSession, call_id)
        if not row: raise HTTPException(status_code=404, detail="Call session not found")
        return _response(row)

def _process(session, row: CallSession, raw: dict):
    parsed = parse_bolna_payload(raw)
    row.status = "ENDED" if parsed.status in {"completed", "call-disconnected", "ended"} else "CONNECTED"
    row.ended_at = utc_now() if row.status == "ENDED" else None
    row.transcript = parsed.transcript; row.extracted = parsed.extracted
    row.validation = {"parse_warnings": parsed.warnings, "fields": validate_extracted(parsed.extracted, row.guardrails)}
    row.outcome_status = parsed.status; row.bolna_execution_id = parsed.execution_id
    session.commit()

@router.post("/webhooks/bolna")
async def receive_bolna_webhook(request: Request, x_voice_adapter_secret: str | None = Header(default=None)):
    expected = settings.bolna_webhook_secret
    if expected and x_voice_adapter_secret != expected: raise HTTPException(status_code=401, detail="Invalid webhook secret")
    raw = await request.json()
    now = utc_now()
    with SessionLocal() as session:
        row = session.execute(select(CallSession).where(CallSession.bolna_execution_id == raw.get("id")).order_by(CallSession.started_at.desc())).scalars().first() if raw.get("id") else None
        vendor, method = resolve_vendor(session, raw.get("extracted_data") if isinstance(raw.get("extracted_data"), dict) else {}, raw.get("user_number"))
        if row is None:
            row = CallSession(id=str(uuid.uuid4()), disruption_id=None, vendor_id=vendor.id if vendor else None, status="RECEIVED", source="LIVE_BOLNA", started_at=now, phone=raw.get("user_number"), correlation_method=method)
            session.add(row); session.flush()
        row.webhook_raw = raw; row.webhook_received_at = now; row.correlation_method = row.correlation_method or method
        session.commit()
        _process(session, row, raw)
        logger.info("bolna_webhook_received", extra={"execution_id": raw.get("id"), "call_id": row.id})
        return {"status": "received", "call_id": row.id}

@router.post("/calls/{call_id}/replay")
def replay_call(call_id: str):
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "bolna_replay.json"
    with fixture.open(encoding="utf-8") as handle: raw = json.load(handle)
    with SessionLocal() as session:
        row = session.get(CallSession, call_id)
        if not row: raise HTTPException(status_code=404, detail="Call session not found")
        row.source = "REPLAY"; row.webhook_raw = raw; row.webhook_received_at = utc_now(); session.flush(); _process(session, row, raw)
        return _response(row)
