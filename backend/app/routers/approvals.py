from fastapi import APIRouter, Depends, HTTPException

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.disruptions import Approval, ApprovalDecisionRequest, ApprovalDecisionResponse
from app.schemas.enums import ApprovalDecision, ApprovalStatus, DisruptionStage, WSEventType
from app.schemas.money import utc_now_iso
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


def _find_disruption_by_approval_id(approval_id: str):
    for d in store.disruptions.values():
        if d.approval is not None and d.approval.id == approval_id:
            return d
    return None


@router.post("/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def decide_approval(approval_id: str, body: ApprovalDecisionRequest) -> ApprovalDecisionResponse:
    cached = store.approval_idempotency.get(body.idempotency_key)
    if cached is not None:
        return ApprovalDecisionResponse.model_validate(cached)

    disruption = _find_disruption_by_approval_id(approval_id)
    if disruption is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    now = utc_now_iso()
    updated_approval = Approval(
        id=disruption.approval.id,
        status=_DECISION_TO_STATUS[body.decision],
        requested_at=disruption.approval.requested_at,
        decided_at=now,
        decided_by=body.decided_by,
        channel=body.channel,
    )
    disruption.approval = updated_approval
    disruption.stage = _DECISION_TO_STAGE[body.decision]

    response = ApprovalDecisionResponse(
        approval=updated_approval,
        disruption_id=disruption.id,
        new_stage=disruption.stage,
    )
    store.approval_idempotency[body.idempotency_key] = response.model_dump()

    await live_feed.broadcast(
        WSEventType.APPROVAL_DECIDED,
        payload={"approval_id": approval_id, "decision": body.decision, "new_stage": disruption.stage},
        disruption_id=disruption.id,
    )
    await live_feed.broadcast(
        WSEventType.STAGE_CHANGED,
        payload={"stage": disruption.stage},
        disruption_id=disruption.id,
    )

    return response
