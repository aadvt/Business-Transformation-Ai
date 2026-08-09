from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db_models import DisruptionEvent
from app.db_models import Negotiation as NegotiationRow
from app.deps import require_api_key
from app.idempotency import get_cached_response, store_response
from app.schemas.enums import DisruptionStage, WSEventType
from app.schemas.money import utc_now
from app.schemas.settlement import NegotiationOutcomeRequest, NegotiationOutcomeResponse
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1/negotiations", tags=["negotiations"], dependencies=[Depends(require_api_key)])


@router.post("/{negotiation_id}/outcome", response_model=NegotiationOutcomeResponse)
async def post_negotiation_outcome(
    negotiation_id: str, body: NegotiationOutcomeRequest, db: AsyncSession = Depends(get_db)
) -> NegotiationOutcomeResponse:
    cached = await get_cached_response(db, body.idempotency_key)
    if cached is not None:
        return NegotiationOutcomeResponse.model_validate(cached)

    negotiation = await db.get(NegotiationRow, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")
    disruption = await db.get(DisruptionEvent, negotiation.disruption_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    negotiation.status = body.outcome
    negotiation.transcript_summary = body.transcript_summary
    if body.final_unit_price_paise is not None:
        negotiation.agreed_unit_price_paise = body.final_unit_price_paise
        negotiation.agreed_lead_time_days = body.final_lead_time_days or 0
        negotiation.agreed_payment_terms_days = body.final_payment_terms_days or 0

    new_stage = DisruptionStage.NEGOTIATED if body.outcome == "AGREED" else DisruptionStage.NEGOTIATING
    disruption.stage = new_stage.value
    if new_stage == DisruptionStage.NEGOTIATED and disruption.negotiated_at is None:
        disruption.negotiated_at = utc_now()

    await db.commit()

    response = NegotiationOutcomeResponse(
        negotiation_id=negotiation_id,
        status=negotiation.status,
        disruption_id=disruption.id,
        new_stage=new_stage,
    )
    await store_response(db, body.idempotency_key, "POST /negotiations/{id}/outcome", response.model_dump())

    await live_feed.broadcast(
        WSEventType.NEGOTIATION_UPDATE,
        payload={"negotiation_id": negotiation_id, "status": negotiation.status},
        disruption_id=disruption.id,
    )
    return response
