from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import get_db
from app.db_models import SettlementBatch as SettlementBatchRow
from app.deps import require_api_key
from app.idempotency import get_cached_response, store_response
from app.schemas.enums import WSEventType
from app.schemas.money import format_inr, utc_now
from app.schemas.settlement import (
    SettlementBatch,
    SettlementBatchList,
    SettlementConfirmRequest,
    SettlementConfirmResponse,
    SettlementExecuteRequest,
    SettlementExecuteResponse,
    SettlementLine,
)
from app.schemas.vendors import VendorRef
from app.transaction_agent_client import stage_settlement_batch
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1", tags=["settlements"], dependencies=[Depends(require_api_key)])


def _to_settlement_batch(b: SettlementBatchRow) -> SettlementBatch:
    # settlement_batches has no created_at/updated_at columns — staged_at is
    # the closest thing to "created", and "updated" is whichever of
    # staged/approved/confirmed happened most recently.
    timestamps = [t for t in (b.staged_at, b.approved_at, b.confirmed_at) if t is not None]
    updated_at = max(timestamps) if timestamps else b.staged_at

    return SettlementBatch(
        id=b.id,
        created_at=b.staged_at.isoformat(),
        updated_at=updated_at.isoformat(),
        month=b.period_month,
        status=b.status,
        total_paise=b.total_paise,
        total_display=format_inr(b.total_paise),
        lines=[
            SettlementLine(
                vendor=VendorRef(id=item.vendor.id, name=item.vendor.name, gstin=item.vendor.gstin),
                invoice_id=item.reference,
                amount_paise=item.amount_paise,
                amount_display=format_inr(item.amount_paise),
                due_date=item.due_date.isoformat() if item.due_date else "",
            )
            for item in b.items
        ],
        confirmed_at=b.confirmed_at.isoformat() if b.confirmed_at else None,
        # No separate confirmed_by column — approved_by is populated by the
        # confirm endpoint below regardless of whether a distinct "approve"
        # step ever ran, so it's the right source for "who confirmed this".
        confirmed_by=b.approved_by,
    )


async def _get_batch(db: AsyncSession, batch_id: str) -> SettlementBatchRow | None:
    stmt = (
        select(SettlementBatchRow)
        .where(SettlementBatchRow.id == batch_id)
        .options(selectinload(SettlementBatchRow.items))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post("/settlements/{batch_id}/execute", response_model=SettlementExecuteResponse)
async def execute_settlement(
    batch_id: str, body: SettlementExecuteRequest, db: AsyncSession = Depends(get_db)
) -> SettlementExecuteResponse:
    cached = await get_cached_response(db, body.idempotency_key)
    if cached is not None:
        return SettlementExecuteResponse.model_validate(cached)

    batch = await _get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Settlement batch not found")

    batch.status = "EXECUTING"
    await db.commit()

    response_batch = _to_settlement_batch(batch)
    handoff = await stage_settlement_batch(response_batch, requested_by=body.executed_by)

    response = SettlementExecuteResponse(batch=response_batch, transaction_agent=handoff)
    await store_response(db, body.idempotency_key, "POST /settlements/{id}/execute", response.model_dump())

    await live_feed.broadcast(
        WSEventType.SETTLEMENT_STAGED,
        payload={"batch_id": batch_id, "status": batch.status, "executed_by": body.executed_by},
    )
    return response


@router.get("/settlement/batch", response_model=SettlementBatchList)
async def get_settlement_batches(
    month: str | None = Query(default=None), db: AsyncSession = Depends(get_db)
) -> SettlementBatchList:
    stmt = (
        select(SettlementBatchRow)
        .where(SettlementBatchRow.org_id == settings.org_id)
        .options(selectinload(SettlementBatchRow.items))
    )
    if month:
        stmt = stmt.where(SettlementBatchRow.period_month == month)
    rows = (await db.execute(stmt)).scalars().all()
    items = [_to_settlement_batch(b) for b in rows]
    return SettlementBatchList(items=items, total=len(items))


@router.post("/settlement/{batch_id}/confirm", response_model=SettlementConfirmResponse)
async def confirm_settlement(
    batch_id: str, body: SettlementConfirmRequest, db: AsyncSession = Depends(get_db)
) -> SettlementConfirmResponse:
    cached = await get_cached_response(db, body.idempotency_key)
    if cached is not None:
        return SettlementConfirmResponse.model_validate(cached)

    batch = await _get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Settlement batch not found")

    batch.status = "CONFIRMED"
    batch.confirmed_at = utc_now()
    batch.approved_by = body.confirmed_by
    await db.commit()

    response = SettlementConfirmResponse(batch=_to_settlement_batch(batch))
    await store_response(db, body.idempotency_key, "POST /settlement/{id}/confirm", response.model_dump())

    await live_feed.broadcast(
        WSEventType.SETTLEMENT_STAGED,
        payload={"batch_id": batch_id, "status": batch.status, "confirmed_by": body.confirmed_by},
    )
    return response
