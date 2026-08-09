from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import disruptions as repo
from app.schemas.disruptions import Disruption, DisruptionList, DisruptionSummary
from app.schemas.enums import DisruptionStage

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
