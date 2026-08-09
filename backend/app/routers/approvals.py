from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db_models import Approval as ApprovalRow
from app.db_models import DisruptionEvent
from app.deps import require_api_key
from app.idempotency import get_cached_response, store_response
from app.schemas.disruptions import Approval, ApprovalDecisionRequest, ApprovalDecisionResponse
from app.schemas.enums import ApprovalDecision, ApprovalStatus, Channel, DisruptionStage, WSEventType
from app.schemas.money import utc_now
from app.ws_manager import live_feed

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"], dependencies=[Depends(require_api_key)])

_DECISION_TO_STATUS = {
    ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
    ApprovalDecision.REJECT: ApprovalStatus.REJECTED,
    ApprovalDecision.REQUEST_OPTIONS: ApprovalStatus.OPTIONS_REQUESTED,
}

_DECISION_TO_STAGE = {
    ApprovalDecision.APPROVE: DisruptionStage.APPROVED,
    ApprovalDecision.REJECT: DisruptionStage.REJECTED,
    ApprovalDecision.REQUEST_OPTIONS: DisruptionStage.SOURCING,
}


@router.post("/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def decide_approval(
    approval_id: str, body: ApprovalDecisionRequest, db: AsyncSession = Depends(get_db)
) -> ApprovalDecisionResponse:
    cached = await get_cached_response(db, body.idempotency_key)
    if cached is not None:
        return ApprovalDecisionResponse.model_validate(cached)

    approval = await db.get(ApprovalRow, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    disruption = await db.get(DisruptionEvent, approval.disruption_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    now = utc_now()
    approval.status = _DECISION_TO_STATUS[body.decision].value
    approval.decided_at = now
    approval.decided_by = body.decided_by
    approval.channel = body.channel.value
    if body.note:
        approval.note = body.note

    new_stage = _DECISION_TO_STAGE[body.decision]
    disruption.stage = new_stage.value
    # Keep the timeline-reconstruction columns (see routers/disruptions.py)
    # consistent with what actually happened.
    if body.decision == ApprovalDecision.APPROVE and disruption.approved_at is None:
        disruption.approved_at = now

    await db.commit()

    response = ApprovalDecisionResponse(
        approval=Approval(
            id=approval.id,
            status=ApprovalStatus(approval.status),
            requested_at=approval.requested_at.isoformat(),
            decided_at=approval.decided_at.isoformat(),
            decided_by=approval.decided_by,
            channel=Channel(approval.channel) if approval.channel else None,
        ),
        disruption_id=disruption.id,
        new_stage=new_stage,
    )
    await store_response(db, body.idempotency_key, "POST /approvals/{id}/decision", response.model_dump())

    await live_feed.broadcast(
        WSEventType.APPROVAL_DECIDED,
        payload={"approval_id": approval_id, "decision": body.decision, "new_stage": new_stage},
        disruption_id=disruption.id,
    )
    await live_feed.broadcast(
        WSEventType.STAGE_CHANGED,
        payload={"stage": new_stage},
        disruption_id=disruption.id,
    )

    return response
