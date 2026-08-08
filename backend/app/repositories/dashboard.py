from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DisruptionEvent, ExposureCalc
from app.repositories.vendors import get_vendor_dues
from app.schemas.dashboard import DashboardSummary, StageCount
from app.schemas.money import format_inr, utc_now_iso

_CLOSED_STAGES = {"CLOSED", "SETTLED", "REJECTED", "FAILED"}
_MITIGATED_STAGES = {"SETTLED", "CLOSED"}


def get_summary(session: Session) -> DashboardSummary:
    rows = session.execute(select(DisruptionEvent)).scalars().all()
    exposure_by_disruption: dict[str, int] = {}
    for calc in session.execute(select(ExposureCalc)).scalars().all():
        # keep the most recently computed exposure per disruption
        exposure_by_disruption[calc.disruption_id] = calc.total_paise

    active = [r for r in rows if r.stage not in _CLOSED_STAGES]
    exposure_at_risk = sum(exposure_by_disruption.get(r.id, 0) for r in active)
    exposure_mitigated = sum(exposure_by_disruption.get(r.id, 0) for r in rows if r.stage in _MITIGATED_STAGES)
    closed_today = sum(1 for r in rows if r.stage in _CLOSED_STAGES)
    stage_counts = Counter(r.stage for r in rows)

    dues = get_vendor_dues(session)

    return DashboardSummary(
        active_disruptions=len(active),
        exposure_at_risk_paise=exposure_at_risk,
        exposure_at_risk_display=format_inr(exposure_at_risk),
        exposure_mitigated_paise=exposure_mitigated,
        exposure_mitigated_display=format_inr(exposure_mitigated),
        disruptions_closed_today=closed_today,
        stage_counts=[StageCount(stage=s, count=c) for s, c in stage_counts.items()],
        vendors_dues_total_paise=dues.total_due_paise,
        vendors_dues_total_display=dues.total_due_display,
        updated_at=utc_now_iso(),
    )
