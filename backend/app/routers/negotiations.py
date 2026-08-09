from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db.session import get_session
from app.deps import require_api_key
from app.mocks.loader import store
from app.repositories import negotiations as repo
from app.schemas.disruptions import NegotiationTerm
from app.schemas.enums import DisruptionStage, WSEventType
from app.schemas.settlement import NegotiationOutcomeRequest, NegotiationOutcomeResponse
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1/negotiations", tags=["negotiations"], dependencies=[Depends(require_api_key)])


def _find_disruption_by_negotiation_id(negotiation_id: str):
    for d in store.disruptions.values():
        if d.negotiation is not None and d.negotiation.id == negotiation_id:
            return d
    return None


def _post_outcome_mock(negotiation_id: str, body: NegotiationOutcomeRequest) -> tuple[NegotiationOutcomeResponse, bool]:
    cached = store.negotiation_outcome_idempotency.get(body.idempotency_key)
    if cached is not None:
        return NegotiationOutcomeResponse.model_validate(cached), True

    disruption = _find_disruption_by_negotiation_id(negotiation_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    negotiation = disruption.negotiation
    negotiation.status = body.outcome
    negotiation.transcript_summary = body.transcript_summary
    if body.final_unit_price_paise is not None:
        negotiation.final_terms = NegotiationTerm(
            unit_price_paise=body.final_unit_price_paise,
            lead_time_days=body.final_lead_time_days or 0,
            payment_terms_days=body.final_payment_terms_days or 0,
        )

    new_stage = DisruptionStage.NEGOTIATED if body.outcome == "AGREED" else DisruptionStage.NEGOTIATING
    disruption.stage = new_stage

    response = NegotiationOutcomeResponse(
        negotiation_id=negotiation_id, status=negotiation.status, disruption_id=disruption.id, new_stage=new_stage,
    )
    store.negotiation_outcome_idempotency[body.idempotency_key] = response.model_dump()
    return response, False


@router.post("/{negotiation_id}/outcome", response_model=NegotiationOutcomeResponse)
async def post_negotiation_outcome(
    negotiation_id: str, body: NegotiationOutcomeRequest, session: Session = Depends(get_session)
) -> NegotiationOutcomeResponse:
    if settings.use_mocks:
        response, is_replay = _post_outcome_mock(negotiation_id, body)
    else:
        response, is_replay = repo.post_outcome(
            session, negotiation_id, body.outcome, body.final_unit_price_paise, body.final_lead_time_days,
            body.final_payment_terms_days, body.transcript_summary, body.idempotency_key, DEFAULT_ORG_ID,
        )
        if response is None:
            raise HTTPException(status_code=404, detail="Negotiation not found")

    if not is_replay:
        await live_feed.broadcast(
            WSEventType.NEGOTIATION_UPDATE,
            payload={"negotiation_id": negotiation_id, "status": response.status},
            disruption_id=response.disruption_id,
        )
    return response
