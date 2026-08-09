from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import audit as repo
from app.schemas.audit import AuditTrail

router = APIRouter(prefix="/api/v1/audit", tags=["audit"], dependencies=[Depends(require_api_key)])


@router.get("/{disruption_id}", response_model=AuditTrail)
def get_audit_trail(disruption_id: str, session: Session = Depends(get_session)) -> AuditTrail:
    if settings.use_mocks:
        if disruption_id not in store.disruptions:
            raise HTTPException(status_code=404, detail="Disruption not found")
        entries = store.audit.get(disruption_id, [])
        return AuditTrail(disruption_id=disruption_id, entries=entries)

    if not repo.disruption_exists(session, disruption_id):
        raise HTTPException(status_code=404, detail="Disruption not found")
    return repo.get_trail(session, disruption_id)
