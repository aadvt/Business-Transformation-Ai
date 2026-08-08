import pytest

from transaction_agent.models import TransactionStatus as S
from transaction_agent.state_machine import (
    IllegalTransitionError,
    is_legal_transition,
    require_legal_transition,
)

LEGAL = [
    (S.CREATED, S.PENDING_APPROVAL),
    (S.PENDING_APPROVAL, S.APPROVED),
    (S.PENDING_APPROVAL, S.REJECTED),
    (S.APPROVED, S.PROCESSING),
    (S.PROCESSING, S.COMPLETED),
    (S.PROCESSING, S.FAILED),
]

ILLEGAL = [
    (S.CREATED, S.APPROVED),
    (S.CREATED, S.PROCESSING),
    (S.CREATED, S.COMPLETED),
    (S.CREATED, S.REJECTED),
    (S.PENDING_APPROVAL, S.PROCESSING),
    (S.PENDING_APPROVAL, S.COMPLETED),
    (S.APPROVED, S.COMPLETED),
    (S.APPROVED, S.REJECTED),
    (S.APPROVED, S.PENDING_APPROVAL),
    (S.PROCESSING, S.APPROVED),
    (S.COMPLETED, S.PROCESSING),
    (S.FAILED, S.PROCESSING),
    (S.REJECTED, S.APPROVED),
    (S.REJECTED, S.PENDING_APPROVAL),
]


@pytest.mark.parametrize("from_status,to_status", LEGAL)
def test_legal_transitions_allowed(from_status, to_status):
    assert is_legal_transition(from_status, to_status)
    require_legal_transition(from_status, to_status)  # must not raise


@pytest.mark.parametrize("from_status,to_status", ILLEGAL)
def test_illegal_transitions_rejected(from_status, to_status):
    assert not is_legal_transition(from_status, to_status)
    with pytest.raises(IllegalTransitionError):
        require_legal_transition(from_status, to_status)


def test_terminal_states_have_no_outgoing_transitions():
    for terminal in (S.COMPLETED, S.FAILED, S.REJECTED):
        for target in S:
            assert not is_legal_transition(terminal, target)
