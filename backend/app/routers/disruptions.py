from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import disruptions as repo
from app.schemas.disruptions import Disruption, DisruptionList, DisruptionSummary
from app.schemas.enums import DisruptionStage
from app.schemas.impact import ImpactGraph
from app.schemas.planner import RemediationPlan
from app.services.impact import get_or_build_impact_graph
from app.db.models import RemediationPlanRow

router = APIRouter(prefix="/api/v1/disruptions", tags=["disruptions"], dependencies=[Depends(require_api_key)])


def _list_disruptions_mock(stage: DisruptionStage | None, limit: int) -> DisruptionList:
    items = list(store.disruptions.values())
    if stage is not None:
        items = [d for d in items if d.stage == stage]
    items = items[:limit]
    summaries = [
        DisruptionSummary(
            id=d.id, type=d.type, stage=d.stage, detected_at=d.detected_at, vendor=d.vendor,
            headline=d.headline, exposure_total_paise=d.exposure.total_paise,
            exposure_total_display=d.exposure.total_display, detector_source=d.detector_source,
        )
        for d in items
    ]
    return DisruptionList(items=summaries, total=len(summaries))


@router.get("", response_model=DisruptionList)
def list_disruptions(
    stage: DisruptionStage | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> DisruptionList:
    if settings.use_mocks:
        return _list_disruptions_mock(stage, limit)
    return repo.list_disruptions(session, stage.value if stage else None, limit)


@router.get("/{disruption_id}", response_model=Disruption)
def get_disruption(disruption_id: str, session: Session = Depends(get_session)) -> Disruption:
    if settings.use_mocks:
        d = store.disruptions.get(disruption_id)
        if d is None:
            raise HTTPException(status_code=404, detail="Disruption not found")
        return d

    d = repo.get_disruption(session, disruption_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Disruption not found")
    return d


@router.get("/{disruption_id}/impact", response_model=ImpactGraph)
def get_disruption_impact(disruption_id: str, session: Session = Depends(get_session)) -> ImpactGraph:
    if settings.use_mocks:
        graph = store.impact_graphs.get(disruption_id)
        if graph is None:
            raise HTTPException(status_code=404, detail="Disruption not found")
        return graph

    disruption = repo.get_disruption_row(session, disruption_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Disruption not found")
    return get_or_build_impact_graph(session, disruption)


@router.get("/{disruption_id}/plan", response_model=RemediationPlan)
def get_disruption_plan(disruption_id: str, session: Session = Depends(get_session)) -> RemediationPlan:
    """Fetch the latest remediation plan for a disruption."""
    from app.schemas.money import format_inr, to_iso

    plan_row = session.query(RemediationPlanRow).filter_by(disruption_id=disruption_id).order_by(RemediationPlanRow.created_at.desc()).first()
    if plan_row is None:
        raise HTTPException(status_code=404, detail="No plan found for this disruption")

    return RemediationPlan(
        id=plan_row.id,
        disruption_id=plan_row.disruption_id,
        created_at=to_iso(plan_row.created_at),
        changes=plan_row.changes,
        before={"exposure_paise": plan_row.before_exposure_paise, "exposure_display": format_inr(plan_row.before_exposure_paise)},
        after={"exposure_paise": plan_row.after_exposure_paise, "exposure_display": format_inr(plan_row.after_exposure_paise)},
        cost_to_resolve_paise=plan_row.cost_to_resolve_paise,
        cost_to_resolve_display=format_inr(plan_row.cost_to_resolve_paise),
        net_saving_paise=plan_row.net_saving_paise,
        net_saving_display=format_inr(plan_row.net_saving_paise),
        requires_escalation=plan_row.requires_escalation,
        escalation_reason=plan_row.escalation_reason,
        solve_ms=plan_row.solve_ms,
        solver=plan_row.solver,
    )
