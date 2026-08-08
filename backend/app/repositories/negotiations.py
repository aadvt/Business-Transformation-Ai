from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DisruptionEvent, Negotiation as NegotiationRow
from app.repositories._idempotency import idempotent
from app.schemas.enums import DisruptionStage
from app.schemas.money import utc_now
from app.schemas.settlement import NegotiationOutcomeResponse
from app.services.audit import append_audit


def post_outcome(
    session: Session,
    negotiation_id: str,
    outcome: str,
    final_unit_price_paise: int | None,
    final_lead_time_days: int | None,
    final_payment_terms_days: int | None,
    transcript_summary: str,
    idempotency_key: str,
    org_id: str,
) -> tuple[NegotiationOutcomeResponse | None, bool]:
    row = session.get(NegotiationRow, negotiation_id)
    if row is None:
        return None, False
    disruption = session.get(DisruptionEvent, row.disruption_id)

    def _do() -> dict:
        row.status = outcome
        row.transcript_summary = transcript_summary
        row.rounds = (row.rounds or 0) + 1
        if final_unit_price_paise is not None:
            row.agreed_unit_price_paise = final_unit_price_paise
            row.agreed_lead_time_days = final_lead_time_days or 0
            row.agreed_payment_terms_days = final_payment_terms_days or 0

        new_stage = DisruptionStage.NEGOTIATED if outcome == "AGREED" else DisruptionStage.NEGOTIATING
        disruption.stage = new_stage
        if outcome == "AGREED" and disruption.negotiated_at is None:
            disruption.negotiated_at = utc_now()

        append_audit(
            session, org_id=org_id, disruption_id=disruption.id, actor_type="AGENT", actor="NEGOTIATION",
            action="NEGOTIATION_OUTCOME_RECORDED", detail={"negotiation_id": negotiation_id, "outcome": outcome},
        )
        session.flush()

        return NegotiationOutcomeResponse(
            negotiation_id=negotiation_id, status=row.status, disruption_id=disruption.id, new_stage=new_stage,
        ).model_dump()

    payload, is_replay = idempotent(session, idempotency_key, "negotiations.outcome", _do)
    return NegotiationOutcomeResponse.model_validate(payload), is_replay
