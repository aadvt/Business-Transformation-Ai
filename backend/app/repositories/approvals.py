from sqlalchemy.orm import Session

from app.db.models import Approval as ApprovalRow, DisruptionEvent
from app.orchestrator.engine import transition
from app.schemas.disruptions import Approval, ApprovalDecisionResponse
from app.schemas.enums import ApprovalDecision, ApprovalStatus
from app.schemas.money import to_iso, utc_now
from app.services.audit import append_audit

_DECISION_TO_STATUS = {
    ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
    ApprovalDecision.REJECT: ApprovalStatus.REJECTED,
    ApprovalDecision.REQUEST_OPTIONS: ApprovalStatus.OPTIONS_REQUESTED,
}
_DECISION_TO_STAGE = {
    ApprovalDecision.APPROVE: "APPROVED",
    ApprovalDecision.REJECT: "REJECTED",
    ApprovalDecision.REQUEST_OPTIONS: "SOURCING",
}


def _to_schema(row: ApprovalRow) -> Approval:
    return Approval(
        id=row.id, status=row.status, requested_at=to_iso(row.requested_at),
        decided_at=to_iso(row.decided_at) if row.decided_at else None,
        decided_by=row.decided_by, channel=row.channel,
    )


def decide_approval(
    session: Session, approval_id: str, decision: str, channel: str, decided_by: str,
    note: str | None, idempotency_key: str, org_id: str,
) -> tuple[ApprovalDecisionResponse | None, bool]:
    """Returns (response, is_replay). is_replay is True when idempotency_key was
    already recorded on this approval — the caller should skip side effects
    (e.g. WS broadcast) it would otherwise perform on a fresh decision."""
    approval = session.get(ApprovalRow, approval_id)
    if approval is None:
        return None, False
    disruption = session.get(DisruptionEvent, approval.disruption_id)

    if approval.idempotency_key == idempotency_key:
        response = ApprovalDecisionResponse(approval=_to_schema(approval), disruption_id=disruption.id, new_stage=disruption.stage)
        return response, True

    now = utc_now()
    approval.status = _DECISION_TO_STATUS[decision]
    approval.decided_at = now
    approval.decided_by = decided_by
    approval.channel = channel
    approval.note = note
    approval.idempotency_key = idempotency_key

    # The state machine (app.orchestrator.engine) is the sole authority on
    # stage changes: AWAITING_APPROVAL -> {APPROVED, REJECTED, SOURCING} are
    # all HUMAN_ONLY transitions, so this call raises IllegalTransitionError
    # if anything ever tries to reach this code path with actor_type != HUMAN.
    transition(
        session, org_id, disruption, _DECISION_TO_STAGE[decision],
        actor_type="HUMAN", actor=decided_by, note=note,
    )

    append_audit(
        session, org_id=org_id, disruption_id=disruption.id, actor_type="HUMAN", actor=decided_by,
        action="APPROVAL_DECIDED", detail={"decision": decision, "channel": channel, "note": note}, at=now,
    )
    session.commit()

    return ApprovalDecisionResponse(approval=_to_schema(approval), disruption_id=disruption.id, new_stage=disruption.stage), False
