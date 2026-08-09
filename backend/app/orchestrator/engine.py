"""Explicit state machine over DisruptionStage. This is the ONLY place a
disruption's stage is allowed to change — agents (Sentinel, Diagnosis,
Sourcing) write their own findings and never touch `disruption.stage`
themselves, precisely so this file can be the single, provable authority on
what transitions are legal and which ones require a human.

Default flow:
    DETECTED -> DIAGNOSED -> SOURCING -> AWAITING_APPROVAL -> (human) ->
    APPROVED -> NEGOTIATING -> NEGOTIATED -> SETTLEMENT_PENDING -> (human) ->
    SETTLED -> CLOSED

Two transitions are HUMAN_ONLY and will raise IllegalTransitionError if an
agent/system actor attempts them: AWAITING_APPROVAL->{APPROVED,REJECTED} (the
approvals endpoint) and SETTLEMENT_PENDING->SETTLED (the settlement confirm
endpoint). This is what makes "there is no code path that skips the human
gate" a provable statement rather than a convention — see
tests/test_state_machine.py.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import DisruptionEvent
from app.schemas.enums import DisruptionStage
from app.schemas.money import utc_now
from app.services.audit import append_audit

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    DisruptionStage.DETECTED: {DisruptionStage.DIAGNOSED, DisruptionStage.FAILED},
    DisruptionStage.DIAGNOSED: {DisruptionStage.SOURCING, DisruptionStage.FAILED},
    DisruptionStage.SOURCING: {DisruptionStage.AWAITING_APPROVAL, DisruptionStage.FAILED},
    # SOURCING is also reachable back from AWAITING_APPROVAL: a human can ask
    # for more/different options (ApprovalDecision.REQUEST_OPTIONS) instead of
    # approving or rejecting outright.
    DisruptionStage.AWAITING_APPROVAL: {DisruptionStage.APPROVED, DisruptionStage.REJECTED, DisruptionStage.SOURCING},
    DisruptionStage.APPROVED: {DisruptionStage.NEGOTIATING, DisruptionStage.FAILED},
    DisruptionStage.REJECTED: {DisruptionStage.CLOSED},
    DisruptionStage.NEGOTIATING: {DisruptionStage.NEGOTIATED, DisruptionStage.FAILED},
    DisruptionStage.NEGOTIATED: {DisruptionStage.SETTLEMENT_PENDING, DisruptionStage.FAILED},
    DisruptionStage.SETTLEMENT_PENDING: {DisruptionStage.SETTLED, DisruptionStage.FAILED},
    DisruptionStage.SETTLED: {DisruptionStage.CLOSED},
    DisruptionStage.CLOSED: set(),
    DisruptionStage.FAILED: set(),
}

# Transitions that must be driven by a human decision, never an agent or the
# scheduler. Enforced in `transition()` — this is not just a convention.
HUMAN_ONLY_TRANSITIONS: set[tuple[str, str]] = {
    (DisruptionStage.AWAITING_APPROVAL, DisruptionStage.APPROVED),
    (DisruptionStage.AWAITING_APPROVAL, DisruptionStage.REJECTED),
    (DisruptionStage.AWAITING_APPROVAL, DisruptionStage.SOURCING),
    (DisruptionStage.SETTLEMENT_PENDING, DisruptionStage.SETTLED),
}

# Which `*_at` columns a transition stamps, keyed by (from, to).
TIMESTAMP_COLUMNS: dict[tuple[str, str], list[str]] = {
    (DisruptionStage.DETECTED, DisruptionStage.DIAGNOSED): ["diagnosed_at"],
    (DisruptionStage.SOURCING, DisruptionStage.AWAITING_APPROVAL): ["sourced_at", "approval_requested_at"],
    (DisruptionStage.AWAITING_APPROVAL, DisruptionStage.APPROVED): ["approved_at"],
    (DisruptionStage.APPROVED, DisruptionStage.NEGOTIATING): ["negotiation_started_at"],
    (DisruptionStage.NEGOTIATING, DisruptionStage.NEGOTIATED): ["negotiated_at"],
    (DisruptionStage.NEGOTIATED, DisruptionStage.SETTLEMENT_PENDING): ["settlement_staged_at"],
    (DisruptionStage.SETTLEMENT_PENDING, DisruptionStage.SETTLED): ["settled_at"],
    (DisruptionStage.SETTLED, DisruptionStage.CLOSED): ["closed_at"],
    (DisruptionStage.REJECTED, DisruptionStage.CLOSED): ["closed_at"],
}


class IllegalTransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransitionResult:
    disruption_id: str
    from_stage: str
    to_stage: str
    at: str


def transition(
    session: Session,
    org_id: str,
    disruption: DisruptionEvent,
    to_stage: str,
    *,
    actor_type: str,
    actor: str,
    note: str | None = None,
) -> TransitionResult:
    from_stage = disruption.stage

    allowed = ALLOWED_TRANSITIONS.get(from_stage, set())
    if to_stage not in allowed:
        raise IllegalTransitionError(f"{from_stage} -> {to_stage} is not an allowed transition")

    if (from_stage, to_stage) in HUMAN_ONLY_TRANSITIONS and actor_type != "HUMAN":
        raise IllegalTransitionError(
            f"{from_stage} -> {to_stage} requires a human decision (actor_type=HUMAN), got actor_type={actor_type}"
        )

    now = utc_now()
    disruption.stage = to_stage
    for column in TIMESTAMP_COLUMNS.get((from_stage, to_stage), []):
        setattr(disruption, column, now)

    append_audit(
        session, org_id=org_id, disruption_id=disruption.id, actor_type=actor_type, actor=actor,
        action="STAGE_CHANGED", detail={"from_stage": from_stage, "to_stage": to_stage, "note": note}, at=now,
    )
    session.commit()

    return TransitionResult(disruption_id=disruption.id, from_stage=from_stage, to_stage=to_stage, at=now.isoformat())
