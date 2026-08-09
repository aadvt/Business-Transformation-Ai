from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import dashboard as repo
from app.schemas.dashboard import DashboardSummary, StageCount
from app.schemas.enums import DisruptionStage
from app.schemas.money import format_inr, utc_now_iso

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"], dependencies=[Depends(require_api_key)])

_CLOSED_STAGES = {DisruptionStage.CLOSED, DisruptionStage.SETTLED, DisruptionStage.REJECTED, DisruptionStage.FAILED}


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(session: Session = Depends(get_session)) -> DashboardSummary:
    if not settings.use_mocks:
        return repo.get_summary(session)

    disruptions = list(store.disruptions.values())
    active = [d for d in disruptions if d.stage not in _CLOSED_STAGES]
    exposure_at_risk = sum(d.exposure.total_paise for d in active)
    exposure_mitigated = sum(
        d.exposure.total_paise for d in disruptions if d.stage in (DisruptionStage.SETTLED, DisruptionStage.CLOSED)
    )
    closed_today = sum(1 for d in disruptions if d.stage in _CLOSED_STAGES)
    stage_counts = Counter(d.stage for d in disruptions)
    dues_total = sum(v.dues_paise for v in store.vendors.values())

    return DashboardSummary(
        active_disruptions=len(active),
        exposure_at_risk_paise=exposure_at_risk,
        exposure_at_risk_display=format_inr(exposure_at_risk),
        exposure_mitigated_paise=exposure_mitigated,
        exposure_mitigated_display=format_inr(exposure_mitigated),
        disruptions_closed_today=closed_today,
        stage_counts=[StageCount(stage=s, count=c) for s, c in stage_counts.items()],
        vendors_dues_total_paise=dues_total,
        vendors_dues_total_display=format_inr(dues_total),
        updated_at=utc_now_iso(),
    )
