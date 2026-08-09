"""SKU forecast. Tries the real TTM (IBM Granite TinyTimeMixer) zero-shot
forecast first; if TTM isn't loaded/available/has too little history for a
given SKU, falls back to a simple linear-trend extrapolation with
`model="RULE_BASED"` — this endpoint must never 500 regardless of TTM's
state. The `model` field is the honest record of which one actually answered;
see README's integration status table and CLAUDE.md.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.detectors import ttm_forecast
from app.db.models import InventorySnapshot
from app.schemas.enums import ForecastModel
from app.schemas.forecast import Forecast, ForecastPoint
from app.schemas.money import to_iso

_HISTORY_DAYS = 14
_FORECAST_DAYS = 7


def _linreg(xs: list[float], ys: list[float]) -> tuple[float, float]:
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs) or 1e-9
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    return slope, mean_y - slope * mean_x


def _get_forecast_ttm(session: Session, sku: str) -> Forecast | None:
    if not ttm_forecast.is_available():
        return None
    # Single-tenant demo — look up by SKU alone rather than threading org_id
    # through the forecast router just for this.
    history_rows = session.execute(
        select(InventorySnapshot)
        .where(InventorySnapshot.sku == sku)
        .order_by(InventorySnapshot.at.desc())
        .limit(600)
    ).scalars().all()
    history_rows = list(reversed(history_rows))
    if not history_rows:
        return None

    result = ttm_forecast.run_forecast(sku, history_rows)
    if result is None:
        return None

    return Forecast(
        sku=sku,
        history=[ForecastPoint(at=to_iso(p.at), value=round(p.value, 1)) for p in result.history[-_HISTORY_DAYS * 24 :]],
        forecast=[ForecastPoint(at=to_iso(p.at), value=round(p.value, 1)) for p in result.forecast],
        reorder_point=result.reorder_point,
        projected_breach_at=to_iso(result.projected_breach_at) if result.projected_breach_at else None,
        model=ForecastModel.TTM,
    )


def _get_forecast_rule_based(session: Session, sku: str) -> Forecast | None:
    rows = session.execute(
        select(InventorySnapshot).where(InventorySnapshot.sku == sku).order_by(InventorySnapshot.at)
    ).scalars().all()
    if not rows:
        return None

    reorder_point = rows[-1].reorder_point

    daily: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        daily[row.at.date().isoformat()].append(row.on_hand_qty)
    daily_avg = {day: sum(vals) / len(vals) for day, vals in sorted(daily.items())}
    recent_days = list(daily_avg.items())[-_HISTORY_DAYS:]

    history = [ForecastPoint(at=f"{day}T12:00:00+00:00", value=round(value, 1)) for day, value in recent_days]

    xs = list(range(len(recent_days)))
    ys = [value for _, value in recent_days]
    slope, intercept = _linreg(xs, ys) if len(recent_days) >= 2 else (0.0, ys[0] if ys else 0.0)

    last_at = rows[-1].at
    forecast: list[ForecastPoint] = []
    projected_breach_at: str | None = None
    for i in range(1, _FORECAST_DAYS + 1):
        value = max(0.0, intercept + slope * (len(recent_days) - 1 + i))
        at = last_at + timedelta(days=i)
        forecast.append(ForecastPoint(at=to_iso(at), value=round(value, 1)))
        if projected_breach_at is None and value <= reorder_point:
            projected_breach_at = to_iso(at)

    return Forecast(
        sku=sku, history=history, forecast=forecast, reorder_point=reorder_point,
        projected_breach_at=projected_breach_at, model="RULE_BASED",
    )


def get_forecast(session: Session, sku: str) -> Forecast | None:
    ttm_result = _get_forecast_ttm(session, sku)
    if ttm_result is not None:
        return ttm_result
    return _get_forecast_rule_based(session, sku)
