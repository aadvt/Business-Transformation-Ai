from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.enums import WSEventType
from app.schemas.money import utc_now_iso
from app.schemas.settlement import (
    SettlementBatchList,
    SettlementConfirmRequest,
    SettlementConfirmResponse,
    SettlementExecuteRequest,
    SettlementExecuteResponse,
)
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1", tags=["settlements"], dependencies=[Depends(require_api_key)])


@router.post("/settlements/{batch_id}/execute", response_model=SettlementExecuteResponse)
async def execute_settlement(batch_id: str, body: SettlementExecuteRequest) -> SettlementExecuteResponse:
    cached = store.settlement_execute_idempotency.get(body.idempotency_key)
    if cached is not None:
        return SettlementExecuteResponse.model_validate(cached)

    batch = store.settlement_batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Settlement batch not found")

    batch.status = "EXECUTING"
    batch.updated_at = utc_now_iso()

    response = SettlementExecuteResponse(batch=batch)
    store.settlement_execute_idempotency[body.idempotency_key] = response.model_dump()

    await live_feed.broadcast(
        WSEventType.SETTLEMENT_STAGED,
        payload={"batch_id": batch_id, "status": batch.status, "executed_by": body.executed_by},
    )
    return response


@router.get("/settlement/batch", response_model=SettlementBatchList)
def get_settlement_batches(month: str | None = Query(default=None)) -> SettlementBatchList:
    items = list(store.settlement_batches.values())
    if month:
        items = [b for b in items if b.month == month]
    return SettlementBatchList(items=items, total=len(items))


@router.post("/settlement/{batch_id}/confirm", response_model=SettlementConfirmResponse)
async def confirm_settlement(batch_id: str, body: SettlementConfirmRequest) -> SettlementConfirmResponse:
    cached = store.settlement_confirm_idempotency.get(body.idempotency_key)
    if cached is not None:
        return SettlementConfirmResponse.model_validate(cached)

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

    await live_feed.broadcast(
        WSEventType.SETTLEMENT_STAGED,
        payload={"batch_id": batch_id, "status": batch.status, "confirmed_by": body.confirmed_by},
    )
    return response
