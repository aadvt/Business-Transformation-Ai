"""D5b call sessions + Bolna post-call webhook.

The Bolna agent is operated manually from its dashboard and reports back only
via a post-call webhook — there is no live transcript stream. The flow here:

  1. POST /calls/start freezes the briefing + guardrails and broadcasts
     CALL_STARTED (the frontend shows the briefing panel during the call).
  2. The webhook lands, raw payload is persisted FIRST, 200 returned
     immediately, then a background task parses and runs the reveal:
     CALL_TRANSCRIPT (one per turn, spaced), CALL_FIELD_EXTRACTED (one per
     field), CALL_ENDED (outcome + Guardian + new stage).
  3. Negotiation write-back + stage transitions + exposure recompute all
     reuse the existing machinery (transition(), compute_exposure()) and are
     fail-soft — a write-back problem never loses the call's data.

Every CALL_TRANSCRIPT event carries phase=POST_CALL_REVEAL — we replay a
completed call's transcript for readability, never pretend it's live.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import func, select

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.models import (
    CallSession,
    DisruptionEvent,
    ExposureCalc,
    Negotiation,
    PurchaseOrder,
    RemediationPlanRow,
    Vendor,
)
from app.db.session import SessionLocal
from app.llm.guardian import GuardianRisk, get_guardian
from app.orchestrator.engine import IllegalTransitionError, transition
from app.repositories.vendors import get_vendor_context
from app.schemas.calls import CallSessionResponse, CallStartRequest
from app.schemas.enums import WSEventType
from app.schemas.money import format_inr, to_iso, utc_now
from app.services.agent_sheet import build_agent_rows, resolve_vendor
from app.services.audit import append_audit
from app.services.bolna import parse_bolna_payload, validate_extracted
from app.services.exposure import AffectedPO, BackupQuote, compute_exposure
from app.ws_manager import live_feed

logger = logging.getLogger("sanjeevani.webhooks")
router = APIRouter(prefix="/api/v1", tags=["calls"])

# Reveal pacing — tune during rehearsal. Total reveal lands around 6-8s for a
# typical 10-turn transcript + 6 fields.
REVEAL_TRANSCRIPT_SPACING_S = 0.35
REVEAL_FIELD_SPACING_S = 0.45
REVEAL_ENDED_DELAY_S = 0.6
# mode=REPLAY on /calls/start waits this long before feeding the fixture, so
# the briefing panel gets its moment on screen during rehearsal.
REPLAY_WEBHOOK_DELAY_S = 8.0

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "bolna_replay.json"


def _load_fixture() -> dict:
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Keep the fixture's "2-day delivery" promise true relative to whenever the
    # replay runs, so the delivery-date validation never rots to "in the past".
    extracted = raw.get("extracted_data")
    if isinstance(extracted, dict) and "delivery_date" in extracted:
        from datetime import timedelta
        extracted["delivery_date"] = (utc_now() + timedelta(days=2)).date().isoformat()
    return raw


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(c for c in phone if c.isdigit())
    return f"+91 ••••• •{digits[-4:]}" if len(digits) >= 4 else "•••"


def _response(row: CallSession) -> CallSessionResponse:
    return CallSessionResponse(
        id=row.id, disruption_id=row.disruption_id, vendor_id=row.vendor_id, status=row.status,
        source=row.source, started_at=to_iso(row.started_at),
        ended_at=to_iso(row.ended_at) if row.ended_at else None, language=row.language,
        phone=_mask_phone(row.phone), briefing_snapshot=row.briefing_snapshot or {},
        guardrails=row.guardrails or {}, transcript=row.transcript or [],
        extracted=row.extracted or {}, validation=row.validation or {},
        correlation_method=row.correlation_method, outcome_status=row.outcome_status,
    )


@router.post("/calls/start", response_model=CallSessionResponse)
async def start_call(body: CallStartRequest):
    with SessionLocal() as session:
        vendor = session.get(Vendor, body.vendor_id)
        disruption = session.get(DisruptionEvent, body.disruption_id)
        if not vendor or not disruption:
            raise HTTPException(status_code=404, detail="Vendor or disruption not found")
        rows = [r for r in build_agent_rows(session, DEFAULT_ORG_ID, body.disruption_id) if r.vendor_id == vendor.id]
        if not rows:
            raise HTTPException(status_code=404, detail="Vendor is not a sourcing candidate")
        snapshot = asdict(rows[0])
        # Guardrails stored in paise so validate_extracted can compare — the
        # sheet row's human-readable strings are for the agent's mouth, not math.
        ctx = get_vendor_context(session, vendor.id)
        guardrails = {
            "max_unit_price_paise": ctx.guardrails.max_unit_price_paise,
            "max_unit_price_display": format_inr(ctx.guardrails.max_unit_price_paise),
            "max_lead_time_days": ctx.guardrails.max_lead_time_days,
        }
        call = CallSession(
            id=str(uuid.uuid4()), disruption_id=body.disruption_id, vendor_id=vendor.id,
            status="DIALING", source="REPLAY" if body.mode == "REPLAY" else "LIVE_BOLNA",
            started_at=utc_now(), language=rows[0].language, phone=vendor.phone,
            briefing_snapshot=snapshot, guardrails=guardrails,
        )
        session.add(call)
        session.commit()
        response = _response(call)

    await live_feed.broadcast(
        WSEventType.CALL_STARTED,
        payload={
            "call_id": response.id, "vendor_id": response.vendor_id, "vendor_name": snapshot["vendor_name"],
            "status": "DIALING", "language": response.language, "phone": response.phone,
            "briefing_snapshot": response.briefing_snapshot, "guardrails": response.guardrails,
            "source": response.source,
        },
        disruption_id=response.disruption_id,
    )
    if body.mode == "REPLAY":
        asyncio.create_task(_replay_after_delay(response.id))
    return response


async def _replay_after_delay(call_id: str) -> None:
    await asyncio.sleep(REPLAY_WEBHOOK_DELAY_S)
    try:
        raw = _load_fixture()
        await _ingest(call_id, raw)
    except Exception:
        logger.exception("replay_after_delay_failed", extra={"call_id": call_id})


@router.get("/calls/{call_id}", response_model=CallSessionResponse)
def get_call(call_id: str):
    with SessionLocal() as session:
        row = session.get(CallSession, call_id)
        if not row:
            raise HTTPException(status_code=404, detail="Call session not found")
        return _response(row)


@router.post("/calls/{call_id}/replay", response_model=CallSessionResponse)
async def replay_call(call_id: str):
    with SessionLocal() as session:
        row = session.get(CallSession, call_id)
        if not row:
            raise HTTPException(status_code=404, detail="Call session not found")
        row.source = "REPLAY"
        session.commit()
    raw = _load_fixture()
    await _ingest(call_id, raw)
    with SessionLocal() as session:
        return _response(session.get(CallSession, call_id))


@router.post("/webhooks/bolna")
async def receive_bolna_webhook(request: Request, x_voice_adapter_secret: str | None = Header(default=None)):
    expected = settings.bolna_webhook_secret
    if expected and x_voice_adapter_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    raw = await request.json()
    # Persist the raw body FIRST and answer 200 — Bolna retries on non-200 and
    # a parser bug must never cause a retry storm mid-demo.
    call_id = await asyncio.to_thread(_store_raw_webhook, raw)
    asyncio.create_task(_ingest(call_id, raw))
    return {"status": "received", "call_id": call_id}


def _store_raw_webhook(raw: dict) -> str:
    now = utc_now()
    with SessionLocal() as session:
        row = None
        if raw.get("id"):
            row = session.execute(
                select(CallSession).where(CallSession.bolna_execution_id == raw.get("id"))
            ).scalars().first()
        if row is None:
            # The live path: /calls/start created a DIALING session that has no
            # execution id yet — the newest one still waiting is ours.
            row = session.execute(
                select(CallSession)
                .where(CallSession.status == "DIALING", CallSession.webhook_raw.is_(None))
                .order_by(CallSession.started_at.desc())
            ).scalars().first()
            if row is not None:
                row.correlation_method = row.correlation_method or "pending_call_session"
        if row is None:
            extracted = raw.get("extracted_data") if isinstance(raw.get("extracted_data"), dict) else {}
            vendor, method = resolve_vendor(session, extracted, raw.get("user_number"))
            row = CallSession(
                id=str(uuid.uuid4()), disruption_id=None, vendor_id=vendor.id if vendor else None,
                status="RECEIVED", source="LIVE_BOLNA", started_at=now,
                phone=raw.get("user_number"), correlation_method=method,
            )
            session.add(row)
            session.flush()
        row.webhook_raw = raw
        row.webhook_received_at = now
        row.bolna_execution_id = raw.get("id") or row.bolna_execution_id
        session.commit()
        logger.info("bolna_webhook_stored", extra={"execution_id": raw.get("id"), "call_id": row.id})
        return row.id


async def _ingest(call_id: str, raw: dict) -> None:
    """Parse + write back on a worker thread, then run the timed reveal."""
    try:
        result = await asyncio.to_thread(_process_call_sync, call_id, raw)
    except Exception:
        logger.exception("bolna_webhook_processing_failed", extra={"call_id": call_id})
        return
    await _reveal(result)


def _process_call_sync(call_id: str, raw: dict) -> dict:
    """Sync (SQLAlchemy + Guardian) — call only via asyncio.to_thread."""
    parsed = parse_bolna_payload(raw)
    with SessionLocal() as session:
        row = session.get(CallSession, call_id)
        guardrails = row.guardrails or {}
        fields = validate_extracted(parsed.extracted, guardrails)
        row.status = "ENDED"
        row.ended_at = utc_now()
        row.transcript = parsed.transcript
        row.extracted = parsed.extracted
        row.validation = {"parse_warnings": parsed.warnings, "fields": fields}
        row.outcome_status = parsed.status
        row.bolna_execution_id = parsed.execution_id or row.bolna_execution_id
        session.commit()

        price = fields.get("unit_price", {})
        price_ok = bool(price.get("valid")) and not price.get("exceeds_guardrail")
        exceeds = bool(price.get("exceeds_guardrail"))

        # Guardian groundedness on the assembled outcome vs the transcript.
        # The outcome claim only includes terms actually SPOKEN on the call —
        # the delivery date is a derived calendar value ("in two days" → an ISO
        # date) that is validated deterministically instead; putting it in the
        # groundedness claim makes an honest checker correctly flag it.
        transcript_text = "\n".join(t.get("text", "") for t in parsed.transcript) or "(no transcript)"
        spoken_terms = []
        if price.get("valid"):
            spoken_terms.append(f"unit price Rs {price['value'] // 100} per unit")
        if fields.get("quantity", {}).get("valid"):
            spoken_terms.append(f"quantity {fields['quantity']['value']} units")
        if fields.get("payment_terms_days", {}).get("valid"):
            terms_days = fields["payment_terms_days"]["value"]
            spoken_terms.append("payment on delivery" if terms_days == 0 else f"payment in {terms_days} days")
        if fields.get("upi_id", {}).get("valid") and fields["upi_id"].get("value"):
            spoken_terms.append(f"via UPI id {fields['upi_id']['value']}")
        outcome_text = f"Agreed terms: {', '.join(spoken_terms)}." if spoken_terms else "No terms were agreed on this call."
        guardian_info = {"status": "UNAVAILABLE", "passed": False, "is_real_guardian": False, "label": "policy check unavailable"}
        try:
            verdict = get_guardian().check(
                outcome_text, risk=GuardianRisk.GROUNDEDNESS, context=transcript_text,
                disruption_id=row.disruption_id,
            )
            guardian_info = {
                "status": verdict.status, "passed": verdict.passed,
                "needs_human_review": verdict.needs_human_review,
                "is_real_guardian": verdict.is_real_guardian,
                # Never describe the surrogate as Granite Guardian (CLAUDE.md).
                "label": ("Granite Guardian" if verdict.is_real_guardian else "policy check")
                + (" passed" if verdict.passed else " flagged review"),
            }
            row.guardian_status = verdict.status
            row.guardian_detail = guardian_info
        except Exception as exc:
            logger.warning("call_guardian_check_failed", extra={"call_id": call_id, "error": str(exc)[:200]})
        session.commit()

        new_stage = None
        exposure_after = None
        if row.disruption_id and row.vendor_id:
            new_stage, exposure_after = _write_back(session, row, fields, parsed, price_ok, exceeds)

        append_audit(
            session, org_id=DEFAULT_ORG_ID, disruption_id=row.disruption_id, actor_type="AGENT",
            actor="NEGOTIATION", action="CALL_OUTCOME_RECORDED",
            detail={
                "call_id": row.id, "correlation_method": row.correlation_method,
                "parse_warnings": parsed.warnings,
                "fields": {k: {"valid": v.get("valid"), "exceeds_guardrail": v.get("exceeds_guardrail", False)} for k, v in fields.items()},
                "guardian": guardian_info.get("label"), "new_stage": new_stage,
            },
        )
        session.commit()

        return {
            "call_id": row.id, "disruption_id": row.disruption_id, "status": row.status,
            "transcript": parsed.transcript, "fields": fields, "guardian": guardian_info,
            "new_stage": new_stage, "exposure_after": exposure_after,
            "outcome_status": "NEEDS_REVIEW" if exceeds else ("CONFIRMED" if price_ok else "INCOMPLETE"),
            "duration_seconds": raw.get("conversation_duration") or 0,
        }


def _write_back(session, row: CallSession, fields: dict, parsed, price_ok: bool, exceeds: bool):
    """Negotiation row + stage transitions + exposure recompute. Fail-soft:
    any failure here logs and returns partial results; the call data itself is
    already committed."""
    new_stage = None
    exposure_after = None
    disruption = session.get(DisruptionEvent, row.disruption_id)
    try:
        negotiation = session.execute(
            select(Negotiation).where(Negotiation.disruption_id == row.disruption_id, Negotiation.vendor_id == row.vendor_id)
        ).scalars().first()
        if negotiation is None:
            negotiation = Negotiation(
                id=str(uuid.uuid4()), disruption_id=row.disruption_id, vendor_id=row.vendor_id,
                status="IN_PROGRESS", started_at=row.started_at, transcript_summary="", rounds=0,
            )
            session.add(negotiation)
            session.flush()
        negotiation.ended_at = row.ended_at
        negotiation.rounds = (negotiation.rounds or 0) + 1
        negotiation.raw_outcome = {"call_id": row.id, "extracted": parsed.extracted}
        negotiation.transcript_summary = (
            " / ".join(t.get("text", "") for t in parsed.transcript[-4:])[:1000] or "Call completed"
        )
        negotiation.guardian_status = row.guardian_status or "PENDING"
        negotiation.guardian_detail = row.guardian_detail or {}
        if price_ok:
            negotiation.agreed_unit_price_paise = fields["unit_price"]["value"]
            negotiation.status = "AGREED"
        elif exceeds:
            negotiation.status = "NEEDS_REVIEW"
        session.commit()

        # Stage advance through the one legal authority. A guardrail breach
        # keeps the disruption where it is — that's the governance story.
        if price_ok and disruption is not None:
            try:
                if disruption.stage == "APPROVED":
                    transition(session, DEFAULT_ORG_ID, disruption, "NEGOTIATING", actor_type="AGENT", actor="NEGOTIATION")
                if disruption.stage == "NEGOTIATING":
                    transition(session, DEFAULT_ORG_ID, disruption, "NEGOTIATED", actor_type="AGENT", actor="NEGOTIATION")
                    new_stage = "NEGOTIATED"
            except IllegalTransitionError as exc:
                logger.warning("call_stage_transition_skipped", extra={"disruption_id": disruption.id, "error": str(exc)})

        # Exposure recompute with the actually-agreed terms: the same
        # compute_exposure formula, fed the residual (plan-uncovered)
        # quantities — mirroring how the planner computes its after-exposure.
        # The negotiated order covers the approved plan's quantities, so the
        # residual blocked value / penalty drop out; if the agreed price were
        # ABOVE the original, the premium would surface honestly.
        if price_ok and disruption is not None and disruption.affected_po_ids:
            pos = session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id.in_(disruption.affected_po_ids))
            ).scalars().all()
            plan = session.execute(
                select(RemediationPlanRow)
                .where(RemediationPlanRow.disruption_id == disruption.id)
                .order_by(RemediationPlanRow.created_at.desc())
            ).scalars().first()
            if pos:
                vendor = session.get(Vendor, row.vendor_id)
                required_qty = sum(po.qty for po in pos if po.delivered_at is None)
                covered_qty = sum(c.get("qty", 0) for c in plan.changes) if plan else 0
                uncovered = max(0.0, 1.0 - (covered_qty / required_qty)) if required_qty > 0 else 1.0
                recomputed = compute_exposure(
                    [
                        AffectedPO(
                            po_id=po.id, po_number=po.po_number,
                            undelivered_qty=round((po.qty if po.delivered_at is None else 0) * uncovered),
                            unit_price_paise=po.unit_price_paise,
                            downstream_order_ref=po.downstream_order_ref,
                            downstream_order_value_paise=po.downstream_order_value_paise if uncovered > 0 else None,
                            penalty_rate_bps=po.penalty_rate_bps if uncovered > 0 else None,
                        )
                        for po in pos
                    ],
                    idle_days=0,
                    daily_line_cost_paise=settings.daily_line_cost_paise,
                    production_critical=False,
                    consumption_rate_known=False,
                    best_backup_quote=BackupQuote(
                        vendor_name=vendor.name if vendor else "backup vendor",
                        unit_price_paise=fields["unit_price"]["value"],
                    ),
                )
                session.add(
                    ExposureCalc(
                        id=str(uuid.uuid4()), disruption_id=disruption.id,
                        total_paise=recomputed.total_paise, confidence=recomputed.confidence,
                        breakdown=[
                            {"label": item.label, "amount_paise": item.amount_paise,
                             "amount_display": format_inr(item.amount_paise), "basis": item.basis}
                            for item in recomputed.breakdown
                        ],
                        inputs=recomputed.inputs, formula_version=recomputed.formula_version,
                        computed_at=utc_now(),
                    )
                )
                session.commit()
                exposure_after = {"total_paise": recomputed.total_paise, "total_display": format_inr(recomputed.total_paise)}
    except Exception:
        logger.exception("call_write_back_failed", extra={"call_id": row.id})
        session.rollback()
    return new_stage, exposure_after


async def _reveal(result: dict) -> None:
    """The post-call reveal: transcript turn by turn, then fields, then the
    outcome. phase=POST_CALL_REVEAL is honest labelling — this is a completed
    call replayed for readability, not a live stream."""
    call_id = result["call_id"]
    disruption_id = result["disruption_id"]
    for turn in result["transcript"]:
        await live_feed.broadcast(
            WSEventType.CALL_TRANSCRIPT,
            payload={"call_id": call_id, "phase": "POST_CALL_REVEAL", **turn},
            disruption_id=disruption_id,
        )
        await asyncio.sleep(REVEAL_TRANSCRIPT_SPACING_S)
    for field_name, info in result["fields"].items():
        await live_feed.broadcast(
            WSEventType.CALL_FIELD_EXTRACTED,
            payload={"call_id": call_id, "field": field_name, **info},
            disruption_id=disruption_id,
        )
        await asyncio.sleep(REVEAL_FIELD_SPACING_S)
    await asyncio.sleep(REVEAL_ENDED_DELAY_S)
    await live_feed.broadcast(
        WSEventType.CALL_ENDED,
        payload={
            "call_id": call_id, "status": "ENDED", "outcome": result["outcome_status"],
            "guardian": result["guardian"], "new_stage": result["new_stage"],
            "exposure_after": result["exposure_after"],
            "duration_seconds": result["duration_seconds"],
        },
        disruption_id=disruption_id,
    )
    if result["new_stage"]:
        await live_feed.broadcast(
            WSEventType.STAGE_CHANGED, payload={"stage": result["new_stage"]}, disruption_id=disruption_id
        )


@router.get("/webhooks/bolna/health")
def bolna_health():
    with SessionLocal() as session:
        row = session.execute(
            select(CallSession).where(CallSession.webhook_received_at.is_not(None)).order_by(CallSession.webhook_received_at.desc())
        ).scalars().first()
        count = session.execute(
            select(func.count()).select_from(CallSession).where(CallSession.webhook_received_at.is_not(None))
        ).scalar_one()
        return {
            "received_count": count,
            "last_received_at": to_iso(row.webhook_received_at) if row else None,
            "healthy": row is not None,
        }
