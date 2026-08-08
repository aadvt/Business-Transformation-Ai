"""Legal state transitions for a Transaction, enforced independently of the graph."""

from __future__ import annotations

from .models import TransactionStatus as S

LEGAL_TRANSITIONS: dict[S, frozenset[S]] = {
    S.CREATED: frozenset({S.PENDING_APPROVAL}),
    S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED}),
    S.APPROVED: frozenset({S.PROCESSING}),
    S.PROCESSING: frozenset({S.COMPLETED, S.FAILED}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
    S.REJECTED: frozenset(),
}


def is_legal_transition(from_status: S, to_status: S) -> bool:
    return to_status in LEGAL_TRANSITIONS.get(from_status, frozenset())


class IllegalTransitionError(ValueError):
    def __init__(self, from_status: S, to_status: S):
        super().__init__(f"Illegal transition: {from_status.value} -> {to_status.value}")
        self.from_status = from_status
        self.to_status = to_status


def require_legal_transition(from_status: S, to_status: S) -> None:
    if not is_legal_transition(from_status, to_status):
        raise IllegalTransitionError(from_status, to_status)
