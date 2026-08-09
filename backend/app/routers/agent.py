import asyncio
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.deps import require_api_key
from app.services.agent_sheet import build_agent_rows, rows_csv, sync_sheet

router = APIRouter(prefix="/api/v1/agent", tags=["agent"], dependencies=[Depends(require_api_key)])

@router.get("/vendor-sheet.csv")
def vendor_sheet_csv(disruption_id: str | None = Query(None), session: Session = Depends(get_session)):
    return Response(rows_csv(build_agent_rows(session, DEFAULT_ORG_ID, disruption_id)), media_type="text/csv")

class SyncRequest(BaseModel):
    disruption_id: str | None = None

@router.post("/sync-sheet")
def sync_vendor_sheet(payload: SyncRequest, session: Session = Depends(get_session)):
    return sync_sheet(session, DEFAULT_ORG_ID, payload.disruption_id)
