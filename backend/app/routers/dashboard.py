from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.db_models import DisruptionEvent
from app.deps import require_api_key
from app.routers.vendors import _dues_by_vendor
from app.schemas.dashboard import DashboardSummary, StageCount
from app.schemas.enums import DisruptionStage
from app.schemas.money import format_inr, utc_now_iso

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(require_api_key)])

_CLOSED_STAGES = {DisruptionStage.CLOSED, DisruptionStage.SETTLED, DisruptionStage.REJECTED, DisruptionStage.FAILED}


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(db: AsyncSession = Depends(get_db)) -> DashboardSummary:
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

    def exposure_paise(d: DisruptionEvent) -> int:
        return d.exposure_calc.total_paise if d.exposure_calc is not None else 0

    active = [d for d in disruptions if d.stage not in _CLOSED_STAGES]
    exposure_at_risk = sum(exposure_paise(d) for d in active)
    exposure_mitigated = sum(
        exposure_paise(d) for d in disruptions if d.stage in (DisruptionStage.SETTLED, DisruptionStage.CLOSED)
    )
    closed_today = sum(1 for d in disruptions if d.stage in _CLOSED_STAGES)
    stage_counts = Counter(d.stage for d in disruptions)

    dues = await _dues_by_vendor(db)
    dues_total = sum(total for total, _count, _oldest in dues.values())

    return DashboardSummary(
        active_disruptions=len(active),
        exposure_at_risk_paise=exposure_at_risk,
        exposure_at_risk_display=format_inr(exposure_at_risk),
        exposure_mitigated_paise=exposure_mitigated,
        exposure_mitigated_display=format_inr(exposure_mitigated),
        disruptions_closed_today=closed_today,
        stage_counts=[StageCount(stage=DisruptionStage(s), count=c) for s, c in stage_counts.items()],
        vendors_dues_total_paise=dues_total,
        vendors_dues_total_display=format_inr(dues_total),
        updated_at=utc_now_iso(),
    )
