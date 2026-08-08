from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import settlements as repo
from app.schemas.enums import WSEventType
from app.schemas.money import utc_now_iso
from app.schemas.settlement import (
    SettlementBatchList,
    SettlementConfirmRequest,
    SettlementConfirmResponse,
    SettlementExecuteRequest,
    SettlementExecuteResponse,
)
from app.transaction_agent_client import stage_settlement_batch
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1", tags=["settlements"], dependencies=[Depends(require_api_key)])


def _execute_mock(batch_id: str, body: SettlementExecuteRequest) -> tuple[SettlementExecuteResponse, bool]:
    cached = store.settlement_execute_idempotency.get(body.idempotency_key)
    if cached is not None:
        return SettlementExecuteResponse.model_validate(cached), True

    batch = store.settlement_batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Settlement batch not found")

    batch.status = "EXECUTING"
    batch.updated_at = utc_now_iso()

    handoff = await stage_settlement_batch(batch, requested_by=body.executed_by)

    response = SettlementExecuteResponse(batch=batch, transaction_agent=handoff)
    store.settlement_execute_idempotency[body.idempotency_key] = response.model_dump()
    return response, False


@router.post("/settlements/{batch_id}/execute", response_model=SettlementExecuteResponse)
async def execute_settlement(
    batch_id: str, body: SettlementExecuteRequest, session: Session = Depends(get_session)
) -> SettlementExecuteResponse:
    if settings.use_mocks:
        response, is_replay = _execute_mock(batch_id, body)
    else:
        response, is_replay = repo.execute_batch(session, batch_id, body.idempotency_key, body.executed_by, DEFAULT_ORG_ID)
        if response is None:
            raise HTTPException(status_code=404, detail="Settlement batch not found")

    if not is_replay:
        await live_feed.broadcast(
            WSEventType.SETTLEMENT_STAGED,
            payload={"batch_id": batch_id, "status": response.batch.status, "executed_by": body.executed_by},
        )
    return response


@router.get("/settlement/batch", response_model=SettlementBatchList)
def get_settlement_batches(month: str | None = Query(default=None), session: Session = Depends(get_session)) -> SettlementBatchList:
    if settings.use_mocks:
        items = list(store.settlement_batches.values())
        if month:
            items = [b for b in items if b.month == month]
        return SettlementBatchList(items=items, total=len(items))
    return repo.list_batches(session, month)


def _confirm_mock(batch_id: str, body: SettlementConfirmRequest) -> tuple[SettlementConfirmResponse, bool]:
    cached = store.settlement_confirm_idempotency.get(body.idempotency_key)
    if cached is not None:
        return SettlementConfirmResponse.model_validate(cached), True

    batch = store.settlement_batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Settlement batch not found")

    now = utc_now_iso()
    batch.status = "CONFIRMED"
    batch.confirmed_at = now
    batch.confirmed_by = body.confirmed_by
    batch.updated_at = now

    response = SettlementConfirmResponse(batch=batch)
    store.settlement_confirm_idempotency[body.idempotency_key] = response.model_dump()
    return response, False


@router.post("/settlement/{batch_id}/confirm", response_model=SettlementConfirmResponse)
async def confirm_settlement(
    batch_id: str, body: SettlementConfirmRequest, session: Session = Depends(get_session)
) -> SettlementConfirmResponse:
    if settings.use_mocks:
        response, is_replay = _confirm_mock(batch_id, body)
    else:
        response, is_replay = repo.confirm_batch(session, batch_id, body.idempotency_key, body.confirmed_by, DEFAULT_ORG_ID)
        if response is None:
            raise HTTPException(status_code=404, detail="Settlement batch not found")

    if not is_replay:
        await live_feed.broadcast(
            WSEventType.SETTLEMENT_STAGED,
            payload={"batch_id": batch_id, "status": response.batch.status, "confirmed_by": body.confirmed_by},
        )
    return response
