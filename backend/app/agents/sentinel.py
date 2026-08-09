"""Sentinel — watches DB state for disruption signals and opens disruption_events.

Deterministic detectors run FIRST and do all the actual detection; the one LLM
call per signal only classifies the already-detected signal into a
`DisruptionType` and writes a short headline. The LLM never decides whether
something is wrong — Python does, from data.

Extension point for Phase 4b's TTM stockout-risk detector: `DETECTORS` is a
plain module-level list of `(session, org_id) -> list[Signal]` callables.
Phase 4b registers one more (`from app.agents.sentinel import DETECTORS;
DETECTORS.append(stockout_risk_detector)`) without editing this file.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agents.base import Agent, AgentContext, AgentResult
from app.config import settings
from app.db.models import CommEvent, DisruptionEvent, PurchaseOrder, Vendor as VendorRow
from app.db.session import SessionLocal
from app.llm import prompts
from app.llm.client import LLMSchemaError, get_llm
from app.schemas.enums import AgentName, AgentStatus, DisruptionType
from app.schemas.money import utc_now
from app.services.audit import append_audit

logger = logging.getLogger("sanjeevani.agents.sentinel")

_OPEN_STAGES = {"DETECTED", "DIAGNOSED", "SOURCING", "AWAITING_APPROVAL", "APPROVED", "NEGOTIATING", "NEGOTIATED", "SETTLEMENT_PENDING"}


@dataclass(frozen=True)
class Signal:
    detector_name: str
    detector_source: str  # RULE_BASED | TTM_FORECAST
    vendor_id: str
    po_ids: list[str]
    evidence: dict
    severity: str  # LOW | MEDIUM | HIGH


# --- detectors ---------------------------------------------------------------
# Each is a pure function of (session, org_id) -> list[Signal]. No LLM, no
# side effects — Sentinel decides what to do with what they find.


def overdue_delivery(session, org_id: str) -> list[Signal]:
    now = utc_now()
    rows = session.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.org_id == org_id,
            PurchaseOrder.delivered_at.is_(None),
            PurchaseOrder.status != "QUALITY_REJECTED",
        )
    ).scalars().all()

    signals: list[Signal] = []
    for po in rows:
        promised_at = po.promised_at if po.promised_at.tzinfo else po.promised_at.replace(tzinfo=now.tzinfo)
        days_late = (now - promised_at).days
        if days_late < settings.overdue_delivery_threshold_days:
            continue
        signals.append(
            Signal(
                detector_name="overdue_delivery",
                detector_source="RULE_BASED",
                vendor_id=po.vendor_id,
                po_ids=[po.id],
                evidence={
                    "po_number": po.po_number,
                    "item_sku": po.item_sku,
                    "days_late": days_late,
                    "promised_at": promised_at.isoformat(),
                    "qty": po.qty,
                    "downstream_order_ref": po.downstream_order_ref,
                },
                severity="HIGH" if days_late >= settings.overdue_delivery_threshold_days * 2 else "MEDIUM",
            )
        )
    return signals


def vendor_silence(session, org_id: str) -> list[Signal]:
    now = utc_now()

    vendors_with_open_pos = session.execute(
        select(PurchaseOrder.vendor_id)
        .where(PurchaseOrder.org_id == org_id, PurchaseOrder.delivered_at.is_(None))
        .distinct()
    ).scalars().all()

    signals: list[Signal] = []
    for vendor_id in vendors_with_open_pos:
        last_inbound = session.execute(
            select(func.max(CommEvent.at)).where(CommEvent.vendor_id == vendor_id, CommEvent.direction == "INBOUND")
        ).scalar_one_or_none()

        if last_inbound is not None:
            last_inbound = last_inbound if last_inbound.tzinfo else last_inbound.replace(tzinfo=now.tzinfo)
            silence_days = (now - last_inbound).days
        else:
            silence_days = settings.vendor_silence_threshold_days + 1  # never heard from -> definitely silent

        if silence_days < settings.vendor_silence_threshold_days:
            continue

        open_po_ids = session.execute(
            select(PurchaseOrder.id).where(PurchaseOrder.vendor_id == vendor_id, PurchaseOrder.delivered_at.is_(None))
        ).scalars().all()

        signals.append(
            Signal(
                detector_name="vendor_silence",
                detector_source="RULE_BASED",
                vendor_id=vendor_id,
                po_ids=list(open_po_ids),
                evidence={
                    "silence_days": silence_days,
                    "last_inbound_at": last_inbound.isoformat() if last_inbound else None,
                    "open_po_count": len(open_po_ids),
                },
                severity="HIGH" if silence_days >= settings.vendor_silence_threshold_days * 1.5 else "MEDIUM",
            )
        )
    return signals


def quality_spike(session, org_id: str) -> list[Signal]:
    window_start = utc_now() - timedelta(days=settings.quality_spike_lookback_days)
    vendor_ids = session.execute(select(VendorRow.id).where(VendorRow.org_id == org_id)).scalars().all()

    signals: list[Signal] = []
    for vendor_id in vendor_ids:
        recent = session.execute(
            select(PurchaseOrder).where(
                PurchaseOrder.vendor_id == vendor_id,
                PurchaseOrder.ordered_at >= window_start,
                PurchaseOrder.status.in_(["DELIVERED", "LATE", "QUALITY_REJECTED"]),
            )
        ).scalars().all()
        if len(recent) < 3:
            continue  # too small a sample to call it a spike, not just noise

        recent_rejected = sum(1 for po in recent if po.status == "QUALITY_REJECTED")
        recent_rate = recent_rejected / len(recent)

        vendor = session.get(VendorRow, vendor_id)
        baseline_rate = (vendor.disputes / vendor.orders_completed) if vendor.orders_completed else 0.0

        if recent_rate == 0 or recent_rate <= baseline_rate * settings.quality_spike_multiplier:
            continue

        rejected_po_ids = [po.id for po in recent if po.status == "QUALITY_REJECTED"]
        signals.append(
            Signal(
                detector_name="quality_spike",
                detector_source="RULE_BASED",
                vendor_id=vendor_id,
                po_ids=rejected_po_ids,
                evidence={
                    "recent_rejection_rate": round(recent_rate, 3),
                    "baseline_rejection_rate": round(baseline_rate, 3),
                    "recent_sample_size": len(recent),
                    "lookback_days": settings.quality_spike_lookback_days,
                },
                severity="HIGH" if recent_rate >= baseline_rate * settings.quality_spike_multiplier * 2 else "MEDIUM",
            )
        )
    return signals


def price_shock(session, org_id: str) -> list[Signal]:
    skus = session.execute(
        select(PurchaseOrder.item_sku).where(PurchaseOrder.org_id == org_id).distinct()
    ).scalars().all()

    signals: list[Signal] = []
    for sku in skus:
        rows = session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.org_id == org_id, PurchaseOrder.item_sku == sku)
            .order_by(PurchaseOrder.ordered_at)
        ).scalars().all()
        if len(rows) < 4:
            continue  # need enough history for a meaningful trailing median

        *prior, latest = rows
        prior_prices = sorted(po.unit_price_paise for po in prior)
        mid = len(prior_prices) // 2
        median = (
            prior_prices[mid] if len(prior_prices) % 2 else (prior_prices[mid - 1] + prior_prices[mid]) / 2
        )
        if median <= 0:
            continue

        uplift_pct = ((latest.unit_price_paise - median) / median) * 100
        if uplift_pct <= settings.price_shock_threshold_pct:
            continue

        signals.append(
            Signal(
                detector_name="price_shock",
                detector_source="RULE_BASED",
                vendor_id=latest.vendor_id,
                po_ids=[latest.id],
                evidence={
                    "sku": sku,
                    "quoted_unit_price_paise": latest.unit_price_paise,
                    "trailing_median_paise": median,
                    "uplift_pct": round(uplift_pct, 1),
                    "sample_size": len(prior_prices),
                },
                severity="HIGH" if uplift_pct >= settings.price_shock_threshold_pct * 2 else "MEDIUM",
            )
        )
    return signals


# Phase 4b appends its TTM stockout-risk detector here without touching this file.
DETECTORS: list[Callable[..., list[Signal]]] = [
    overdue_delivery,
    vendor_silence,
    quality_spike,
    price_shock,
]


class SentinelClassification(BaseModel):
    disruption_type: DisruptionType
    severity: str = Field(pattern="^(LOW|MEDIUM|HIGH)$")
    confidence: float = Field(ge=0.0, le=1.0)
    headline: str = Field(max_length=90)


def _already_open(session, vendor_id: str, detector_name: str) -> bool:
    """Dedup: don't re-raise a disruption every scheduler tick for a signal
    that's already open and being worked."""
    existing = session.execute(
        select(DisruptionEvent.id).where(
            DisruptionEvent.vendor_id == vendor_id,
            DisruptionEvent.detector_name == detector_name,
            DisruptionEvent.stage.in_(_OPEN_STAGES),
        )
    ).first()
    return existing is not None


class SentinelAgent(Agent):
    name = AgentName.SENTINEL

    def _execute(self, ctx: AgentContext) -> AgentResult:
        session = ctx.session
        org_id = ctx.org_id

        raw_signals: list[Signal] = []
        for detector in DETECTORS:
            raw_signals.extend(detector(session, org_id))

        new_signals = [s for s in raw_signals if not _already_open(session, s.vendor_id, s.detector_name)]

        if not new_signals:
            return AgentResult(
                status=AgentStatus.DONE,
                summary=f"Scanned {len(DETECTORS)} detectors, {len(raw_signals)} signal(s) found, none new.",
                data={"created_disruption_ids": [], "signals_found": len(raw_signals)},
            )

        llm = get_llm()
        created_ids: list[str] = []

        for signal in new_signals:
            vendor = session.get(VendorRow, signal.vendor_id)
            vendor_name = vendor.name if vendor else "Unknown vendor"

            user_prompt = (
                f"Detector: {signal.detector_name}\n"
                f"Vendor: {vendor_name}\n"
                f"Severity (from data): {signal.severity}\n"
                f"Evidence: {signal.evidence}"
            )

            try:
                result = llm.complete(
                    prompts.SENTINEL_CLASSIFY_V1,
                    user_prompt,
                    schema=SentinelClassification,
                    tag=prompts.TAG_SENTINEL_CLASSIFY,
                    max_tokens=300,
                )
                classification = result.parsed
            except LLMSchemaError:
                # Fall back to a deterministic classification so one bad model
                # response can't stop the disruption from being opened.
                classification = SentinelClassification(
                    disruption_type=_fallback_type_for_detector(signal.detector_name),
                    severity=signal.severity,
                    confidence=0.4,
                    headline=f"{signal.detector_name.replace('_', ' ').title()} detected for {vendor_name}"[:90],
                )

            disruption_id = str(uuid.uuid4())
            now = utc_now()
            session.add(
                DisruptionEvent(
                    id=disruption_id,
                    org_id=org_id,
                    type=classification.disruption_type.value,
                    stage="DETECTED",
                    vendor_id=signal.vendor_id,
                    detected_at=now,
                    headline=classification.headline,
                    signal_payload=signal.evidence,
                    detector_name=signal.detector_name,
                    detector_source=signal.detector_source,
                    affected_po_ids=signal.po_ids,
                )
            )
            session.flush()

            append_audit(
                session, org_id=org_id, disruption_id=disruption_id, actor_type="AGENT", actor="SENTINEL",
                action="SIGNAL_RAISED",
                detail={"detector_name": signal.detector_name, "vendor_id": signal.vendor_id, **signal.evidence},
                at=now,
            )
            created_ids.append(disruption_id)

        return AgentResult(
            status=AgentStatus.DONE,
            summary=f"Opened {len(created_ids)} new disruption(s) from {len(raw_signals)} signal(s).",
            data={"created_disruption_ids": created_ids, "signals_found": len(raw_signals)},
        )

    def run_once(self, session, org_id: str) -> AgentResult:
        return self.run(AgentContext(session=session, org_id=org_id))


_FALLBACK_TYPE_BY_DETECTOR = {
    "overdue_delivery": DisruptionType.DELIVERY_DELAY,
    "vendor_silence": DisruptionType.VENDOR_UNRESPONSIVE,
    "quality_spike": DisruptionType.QUALITY_REJECTION,
    "price_shock": DisruptionType.PRICE_SHOCK,
}


def _fallback_type_for_detector(detector_name: str) -> DisruptionType:
    return _FALLBACK_TYPE_BY_DETECTOR.get(detector_name, DisruptionType.DELIVERY_DELAY)


def _run_once_sync(agent: "SentinelAgent", org_id: str) -> None:
    with SessionLocal() as session:
        agent.run_once(session, org_id)


async def run_sentinel_loop(org_id: str) -> None:
    """Background scheduler loop — a fresh session per tick, never held across
    the sleep interval.

    `SentinelAgent.run_once` is fully synchronous (sync SQLAlchemy session,
    blocking httpx calls to watsonx for classification) and can easily take
    30-60s when several signals need classifying. Calling it directly on the
    event loop would stall EVERY other request the server is handling for that
    entire span — `asyncio.to_thread` runs it on a worker thread instead, so a
    demo user's API calls stay responsive while a tick is in flight.
    """
    agent = SentinelAgent()
    while True:
        await asyncio.sleep(settings.sentinel_interval_seconds)
        try:
            await asyncio.to_thread(_run_once_sync, agent, org_id)
        except Exception:
            logger.error("sentinel_loop_tick_failed", exc_info=True)
