"""TTM (IBM Granite TinyTimeMixer) stockout-risk detector.

Additive to Phase 4a's Sentinel: registered into `app.agents.sentinel.DETECTORS`
from outside that module (see the bottom of this file and
`app/main.py`'s startup), so the existing rule-based detectors are never
touched and keep working regardless of whether this one is available.

The model is loaded ONCE, in a background thread, at FastAPI startup —
`start_background_load()` schedules it and returns immediately; nothing here
ever loads a model inside a request handler. If loading fails for any reason
(no cached weights, no internet, incompatible torch build), `TTM_AVAILABLE`
stays False and `stockout_risk_ttm()` returns no signals — Sentinel's
rule-based detectors are completely unaffected. `ENABLE_TTM_DETECTOR=false`
short-circuits all of this instantly, no redeploy needed.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import sentinel
from app.agents.sentinel import Signal
from app.config import settings
from app.db.models import InventorySnapshot, PurchaseOrder, Vendor as VendorRow
from app.llm.runs import default_recorder, truncate
from app.schemas.money import as_utc, utc_now

logger = logging.getLogger("sanjeevani.agents.ttm")

DETECTOR_NAME = "ttm_stockout_forecast"

TTM_AVAILABLE = False
_model = None
_model_lock = threading.Lock()

# There is no formal SKU -> supplying-vendor table in the schema yet (Phase 5+
# territory). inventory_snapshots is a pure consumption/stock series with no
# vendor_id, but Signal/DisruptionEvent both require one — this is the
# deliberately-documented seam: a stockout-risk signal is attributed to
# whichever seeded vendor is that SKU's supplier by naming convention. Keep
# this in sync with app/seed.py's INVENTORY_SKUS and vendor list.
SKU_VENDOR_HINTS: dict[str, str] = {
    "CRS-2MM": "Marudhar Steel Traders",
    "FST-M8-BOLT": "Shree Balaji Auto Components",
    "RBR-SEAL-A": "Anand Rubber Seals Pvt Ltd",
    "WHS-HARN-12V": "Suryodaya Wiring Systems",
    "MCH-SHAFT-22": "Kohinoor Precision Pvt Ltd",
    "PKG-BOX-L": "Sundaram Logistics & Freight",
    "PWD-COAT-BLK": "Bhavani Powder Coatings",
    "CST-BRKT-07": "Bharat Casting Industries",
    "RBR-GASKET-C": "Deccan Elastomers",
    "FST-M6-NUT": "Om Fasteners Pvt Ltd",
}


def load_model() -> None:
    """Synchronous, potentially slow (network + weight load). Call only via
    `start_background_load()` — never on the event loop, never per-request."""
    global _model, TTM_AVAILABLE
    if not settings.enable_ttm_detector:
        logger.info("ttm_detector_disabled_by_config")
        return
    try:
        from tsfm_public.models.tinytimemixer import TinyTimeMixerForPrediction

        start = time.monotonic()
        model = TinyTimeMixerForPrediction.from_pretrained(settings.ttm_model_id)
        model.eval()
        with _model_lock:
            _model = model
            TTM_AVAILABLE = True
        logger.info(
            "ttm_model_loaded",
            extra={"model_id": settings.ttm_model_id, "latency_ms": round((time.monotonic() - start) * 1000, 1)},
        )
    except Exception:
        with _model_lock:
            TTM_AVAILABLE = False
        logger.warning(
            "ttm_model_load_failed_detector_disabled",
            extra={"model_id": settings.ttm_model_id},
            exc_info=True,
        )


async def start_background_load() -> None:
    """Fire-and-forget: schedules `load_model()` on a worker thread and
    returns immediately, so app startup is never held up waiting on a
    Hugging Face Hub round-trip or weight deserialization."""
    import asyncio

    asyncio.create_task(asyncio.to_thread(load_model))


def is_available() -> bool:
    return TTM_AVAILABLE


@dataclass(frozen=True)
class ForecastPoint:
    at: datetime
    value: float


@dataclass(frozen=True)
class TTMForecastResult:
    sku: str
    history: list[ForecastPoint]
    forecast: list[ForecastPoint]
    reorder_point: float
    projected_breach_at: datetime | None
    model_id: str
    latency_ms: float


def find_projected_breach(forecast: list[ForecastPoint], reorder_point: float) -> datetime | None:
    """Pure: the first forecast step (if any) at or below reorder_point. No
    model needed — this is the part of the detector that's fully unit-testable
    without cached weights or a network connection."""
    return next((p.at for p in forecast if p.value <= reorder_point), None)


def fetch_history(session: Session, org_id: str, sku: str, limit: int = 512) -> list[InventorySnapshot]:
    rows = session.execute(
        select(InventorySnapshot)
        .where(InventorySnapshot.org_id == org_id, InventorySnapshot.sku == sku)
        .order_by(InventorySnapshot.at.desc())
        .limit(limit)
    ).scalars().all()
    return list(reversed(rows))  # ascending chronological order


def run_forecast(sku: str, history_rows: list[InventorySnapshot]) -> TTMForecastResult | None:
    """Pure-ish: given already-fetched rows, runs zero-shot inference and
    finds the first forecast step (if any) at or below reorder_point. Returns
    None if TTM isn't loaded or there isn't enough history for the model's
    context window."""
    if not TTM_AVAILABLE or _model is None:
        return None
    if len(history_rows) < settings.ttm_context_length:
        return None

    import torch

    window = history_rows[-settings.ttm_context_length :]
    values = [row.on_hand_qty for row in window]
    reorder_point = window[-1].reorder_point

    last_at = as_utc(window[-1].at)
    prev_at = as_utc(window[-2].at)
    step = last_at - prev_at

    start = time.monotonic()
    past_values = torch.tensor(values, dtype=torch.float32).reshape(1, settings.ttm_context_length, 1)
    with torch.no_grad():
        output = _model(past_values=past_values)
    predicted = output.prediction_outputs.squeeze(0).squeeze(-1).tolist()
    latency_ms = (time.monotonic() - start) * 1000

    history = [ForecastPoint(at=as_utc(row.at), value=row.on_hand_qty) for row in window]
    forecast = [ForecastPoint(at=last_at + step * (i + 1), value=float(v)) for i, v in enumerate(predicted)]

    projected_breach_at = find_projected_breach(forecast, reorder_point)

    return TTMForecastResult(
        sku=sku,
        history=history,
        forecast=forecast,
        reorder_point=reorder_point,
        projected_breach_at=projected_breach_at,
        model_id=settings.ttm_model_id,
        latency_ms=latency_ms,
    )


def _resolve_vendor_id(session: Session, org_id: str, sku: str) -> str | None:
    vendor_name = SKU_VENDOR_HINTS.get(sku)
    if vendor_name is None:
        return None
    vendor = session.execute(
        select(VendorRow).where(VendorRow.org_id == org_id, VendorRow.name == vendor_name)
    ).scalar_one_or_none()
    return vendor.id if vendor else None


def _record_run(sku: str, result: TTMForecastResult | None, error: str | None, started_at: datetime) -> None:
    recorder = default_recorder()
    ended_at = utc_now()
    if result is not None:
        output_summary = (
            f"reorder_point={result.reorder_point}, projected_breach_at={result.projected_breach_at}, "
            f"forecast_min={min(p.value for p in result.forecast):.1f}"
        )
        latency_ms = result.latency_ms
        status = "DONE"
    else:
        output_summary = ""
        latency_ms = (ended_at - started_at).total_seconds() * 1000
        status = "ERROR" if error else "DONE"

    recorder.record(
        agent=f"TTM_FORECAST_{sku}"[:30],
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        latency_ms=latency_ms,
        model_id=settings.ttm_model_id,
        input_summary=truncate(f"sku={sku}, context_length={settings.ttm_context_length}"),
        output_summary=truncate(output_summary),
        error=error,
        token_usage=None,
    )


def stockout_risk_ttm(session: Session, org_id: str) -> list["Signal"]:
    """Sentinel-compatible detector: (session, org_id) -> list[Signal]. Returns
    [] immediately if the model isn't available or the flag is off — never
    raises, so a TTM problem can never take down the rest of Sentinel's scan."""
    if not settings.enable_ttm_detector or not TTM_AVAILABLE:
        return []

    skus = session.execute(
        select(InventorySnapshot.sku).where(InventorySnapshot.org_id == org_id).distinct()
    ).scalars().all()

    signals: list[Signal] = []
    for sku in skus:
        started_at = utc_now()
        try:
            history_rows = fetch_history(session, org_id, sku)
            result = run_forecast(sku, history_rows)
        except Exception as exc:
            logger.error("ttm_forecast_failed", extra={"sku": sku}, exc_info=True)
            _record_run(sku, None, f"{type(exc).__name__}: {exc}", started_at)
            continue

        if result is None:
            continue
        _record_run(sku, result, None, started_at)

        if result.projected_breach_at is None:
            continue

        vendor_id = _resolve_vendor_id(session, org_id, sku)
        if vendor_id is None:
            logger.warning("ttm_signal_dropped_no_vendor_mapping", extra={"sku": sku})
            continue

        horizon_fraction = (
            result.forecast.index(next(p for p in result.forecast if p.at == result.projected_breach_at))
            / len(result.forecast)
        )
        severity = "HIGH" if horizon_fraction <= 0.25 else "MEDIUM"

        signals.append(
            Signal(
                detector_name=DETECTOR_NAME,
                detector_source="TTM_FORECAST",
                vendor_id=vendor_id,
                po_ids=[],
                evidence={
                    "sku": sku,
                    "model": settings.ttm_model_id,
                    "reorder_point": result.reorder_point,
                    "current_on_hand": result.history[-1].value,
                    "projected_breach_at": result.projected_breach_at.isoformat(),
                    "forecast_horizon_steps": len(result.forecast),
                    "forecast_min_value": min(p.value for p in result.forecast),
                    "inference_latency_ms": round(result.latency_ms, 1),
                },
                severity=severity,
            )
        )

    return signals


# --- additive registration into Phase 4a's Sentinel, per its own documented
# extension point (app/agents/sentinel.py's module docstring) — this is the
# ONLY line that touches Sentinel, and it never edits that file.
if stockout_risk_ttm not in sentinel.DETECTORS:
    sentinel.DETECTORS.append(stockout_risk_ttm)
