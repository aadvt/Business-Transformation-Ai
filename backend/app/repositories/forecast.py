"""SKU forecast — derives history + a simple linear trend forecast from
inventory_snapshots. `model` is always RULE_BASED in Phase 2: the real TTM
(granite-timeseries-ttm-r2) integration is still STUB (see README's
integration status table), so claiming otherwise here would be dishonest.
The `detector_source`/`model` distinction exists precisely so the frontend can
show this provenance once TTM actually goes LIVE.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InventorySnapshot
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


def get_forecast(session: Session, sku: str) -> Forecast | None:
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
