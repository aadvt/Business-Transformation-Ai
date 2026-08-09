from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.db_models import AgentRun, DisruptionEvent
from app.deps import require_api_key
from app.schemas.enums import DisruptionStage, IntegrationStatus
from app.schemas.metrics import Integrations, Latency, LatencyStat, MetricsDemo, Totals
from app.schemas.money import format_inr

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"], dependencies=[Depends(require_api_key)])

_MITIGATED_STAGES = {DisruptionStage.SETTLED.value, DisruptionStage.CLOSED.value}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * pct), len(ordered) - 1)
    return ordered[idx]


def _latency_stat(values: list[float]) -> LatencyStat:
    return LatencyStat(p50=_percentile(values, 0.5), p95=_percentile(values, 0.95), last=values[-1] if values else 0.0)


@router.get("/demo", response_model=MetricsDemo)
async def get_metrics_demo(db: AsyncSession = Depends(get_db)) -> MetricsDemo:
    disruptions = (
        (
            await db.execute(
                select(DisruptionEvent)
                .where(DisruptionEvent.org_id == settings.org_id)
                .options(selectinload(DisruptionEvent.exposure_calc))
            )
        )
        .scalars()
        .all()
    )

    def exposure(d: DisruptionEvent) -> int:
        return d.exposure_calc.total_paise if d.exposure_calc else 0

    exposure_identified = sum(exposure(d) for d in disruptions)
    exposure_mitigated = sum(exposure(d) for d in disruptions if d.stage in _MITIGATED_STAGES)
    disruptions_closed = sum(1 for d in disruptions if d.stage in _MITIGATED_STAGES)

    # Only end-to-end has a real source (agent_runs.latency_ms) — the other
    # three buckets would need a bespoke stage-to-stage timestamp formula
    # that isn't part of this pass's scope; zero-filled rather than guessed.
    run_latencies_ms = [
        ms
        for (ms,) in (
            await db.execute(select(AgentRun.latency_ms).where(AgentRun.latency_ms.is_not(None)))
        ).all()
    ]

    return MetricsDemo(
        latency=Latency(
            detection_to_alert_seconds=_latency_stat([]),
            alert_to_decision_seconds=_latency_stat([]),
            decision_to_negotiated_seconds=_latency_stat([]),
            end_to_end_seconds=_latency_stat([ms / 1000 for ms in run_latencies_ms]),
        ),
        totals=Totals(
            exposure_identified_paise=exposure_identified,
            exposure_identified_display=format_inr(exposure_identified),
            exposure_mitigated_paise=exposure_mitigated,
            exposure_mitigated_display=format_inr(exposure_mitigated),
            disruptions_closed=disruptions_closed,
        ),
        integrations=Integrations(
            watsonx=IntegrationStatus.STUB,
            guardian=IntegrationStatus.STUB,
            supermemory=IntegrationStatus.STUB,
            verification=IntegrationStatus.STUB,
            ttm=IntegrationStatus.STUB,
            orchestrate=IntegrationStatus.NOT_CONFIGURED,
            neon=IntegrationStatus.LIVE,
        ),
    )
