"""Orchestrator state machine tests. Every legal transition passes, a
representative set of illegal ones raise, and — the property that matters
most — there is no code path that reaches NEGOTIATING or SETTLED without a
human decision.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import DisruptionEvent, Organisation, Vendor
from app.orchestrator.engine import ALLOWED_TRANSITIONS, HUMAN_ONLY_TRANSITIONS, IllegalTransitionError, transition
from app.schemas.enums import DisruptionStage
from app.schemas.money import utc_now


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    s.add(Organisation(id="org1", name="T", city="Pune", industry="x", revenue_cr=1.0, lat=1.0, lng=1.0, created_at=utc_now()))
    s.add(Vendor(
        id="v1", org_id="org1", name="Test Vendor", category="X", gstin="27AABCS1429B1ZP",
        udyam_number=None, phone="+91", email="a@b.com", city="Pune", state="Maharashtra",
        lat=1.0, lng=1.0, languages=[], reliability_score=80, on_time_rate=0.9, orders_completed=5,
        disputes=0, avg_lead_time_days=3.0, is_backup_pool=False, payment_terms_days=30,
        created_at=utc_now(), updated_at=utc_now(),
    ))
    s.flush()
    yield s
    s.close()


def make_disruption(session, stage: str) -> DisruptionEvent:
    d = DisruptionEvent(
        id=f"d-{stage}-{id(object())}", org_id="org1", type="DELIVERY_DELAY", stage=stage,
        vendor_id="v1", detected_at=utc_now(), headline="Test disruption",
        signal_payload={}, detector_name="overdue_delivery", detector_source="RULE_BASED", affected_po_ids=[],
    )
    session.add(d)
    session.flush()
    return d


# --- every legal transition passes --------------------------------------------


@pytest.mark.parametrize(
    "from_stage,to_stage",
    [(f, t) for f, targets in ALLOWED_TRANSITIONS.items() for t in targets],
)
def test_every_allowed_transition_succeeds(session, from_stage, to_stage):
    d = make_disruption(session, from_stage)
    actor_type = "HUMAN" if (from_stage, to_stage) in HUMAN_ONLY_TRANSITIONS else "AGENT"
    result = transition(session, "org1", d, to_stage, actor_type=actor_type, actor="tester")
    assert d.stage == to_stage
    assert result.from_stage == from_stage
    assert result.to_stage == to_stage


# --- illegal transitions raise -------------------------------------------------


@pytest.mark.parametrize(
    "from_stage,to_stage",
    [
        (DisruptionStage.DETECTED, DisruptionStage.SETTLED),
        (DisruptionStage.DETECTED, DisruptionStage.NEGOTIATING),
        (DisruptionStage.DIAGNOSED, DisruptionStage.AWAITING_APPROVAL),
        (DisruptionStage.SOURCING, DisruptionStage.NEGOTIATING),
        (DisruptionStage.AWAITING_APPROVAL, DisruptionStage.NEGOTIATING),
        (DisruptionStage.APPROVED, DisruptionStage.SETTLED),
        (DisruptionStage.CLOSED, DisruptionStage.DETECTED),
        (DisruptionStage.SETTLED, DisruptionStage.NEGOTIATING),
    ],
)
def test_illegal_transitions_raise(session, from_stage, to_stage):
    d = make_disruption(session, from_stage)
    with pytest.raises(IllegalTransitionError):
        transition(session, "org1", d, to_stage, actor_type="AGENT", actor="tester")
    assert d.stage == from_stage, "stage must not change on a rejected transition"


def test_terminal_stages_have_no_outgoing_transitions():
    assert ALLOWED_TRANSITIONS[DisruptionStage.CLOSED] == set()
    assert ALLOWED_TRANSITIONS[DisruptionStage.FAILED] == set()


# --- the human gate cannot be bypassed -----------------------------------------


@pytest.mark.parametrize("actor_type", ["AGENT", "SYSTEM"])
def test_approval_decision_requires_human_actor(session, actor_type):
    d = make_disruption(session, DisruptionStage.AWAITING_APPROVAL)
    with pytest.raises(IllegalTransitionError, match="requires a human decision"):
        transition(session, "org1", d, DisruptionStage.APPROVED, actor_type=actor_type, actor="not-a-human")
    assert d.stage == DisruptionStage.AWAITING_APPROVAL


@pytest.mark.parametrize("actor_type", ["AGENT", "SYSTEM"])
def test_rejection_requires_human_actor(session, actor_type):
    d = make_disruption(session, DisruptionStage.AWAITING_APPROVAL)
    with pytest.raises(IllegalTransitionError, match="requires a human decision"):
        transition(session, "org1", d, DisruptionStage.REJECTED, actor_type=actor_type, actor="not-a-human")


@pytest.mark.parametrize("actor_type", ["AGENT", "SYSTEM"])
def test_settlement_confirmation_requires_human_actor(session, actor_type):
    d = make_disruption(session, DisruptionStage.SETTLEMENT_PENDING)
    with pytest.raises(IllegalTransitionError, match="requires a human decision"):
        transition(session, "org1", d, DisruptionStage.SETTLED, actor_type=actor_type, actor="not-a-human")


def test_human_actor_can_approve(session):
    d = make_disruption(session, DisruptionStage.AWAITING_APPROVAL)
    transition(session, "org1", d, DisruptionStage.APPROVED, actor_type="HUMAN", actor="priya@shakti-auto.in")
    assert d.stage == DisruptionStage.APPROVED
    assert d.approved_at is not None


def test_human_actor_can_confirm_settlement(session):
    d = make_disruption(session, DisruptionStage.SETTLEMENT_PENDING)
    transition(session, "org1", d, DisruptionStage.SETTLED, actor_type="HUMAN", actor="finance@shakti-auto.in")
    assert d.stage == DisruptionStage.SETTLED
    assert d.settled_at is not None


def test_negotiating_is_reachable_only_from_approved():
    """Structural guarantee: no stage other than APPROVED has NEGOTIATING as a
    legal target, so nothing can reach it without first passing through the
    human-gated AWAITING_APPROVAL -> APPROVED step."""
    stages_that_can_reach_negotiating = [
        stage for stage, targets in ALLOWED_TRANSITIONS.items() if DisruptionStage.NEGOTIATING in targets
    ]
    assert stages_that_can_reach_negotiating == [DisruptionStage.APPROVED]


def test_settled_is_reachable_only_from_settlement_pending_and_human_gated():
    stages_that_can_reach_settled = [
        stage for stage, targets in ALLOWED_TRANSITIONS.items() if DisruptionStage.SETTLED in targets
    ]
    assert stages_that_can_reach_settled == [DisruptionStage.SETTLEMENT_PENDING]
    assert (DisruptionStage.SETTLEMENT_PENDING, DisruptionStage.SETTLED) in HUMAN_ONLY_TRANSITIONS


# --- timestamp stamping ---------------------------------------------------------


def test_transition_stamps_matching_timestamp_column(session):
    d = make_disruption(session, DisruptionStage.DETECTED)
    assert d.diagnosed_at is None
    transition(session, "org1", d, DisruptionStage.DIAGNOSED, actor_type="AGENT", actor="DIAGNOSIS")
    assert d.diagnosed_at is not None


def test_transition_does_not_stamp_unrelated_columns(session):
    d = make_disruption(session, DisruptionStage.DETECTED)
    transition(session, "org1", d, DisruptionStage.DIAGNOSED, actor_type="AGENT", actor="DIAGNOSIS")
    assert d.approved_at is None
    assert d.settled_at is None


def test_transition_writes_audit_log_entry(session):
    from app.db.models import AuditLogEntry

    d = make_disruption(session, DisruptionStage.DETECTED)
    transition(session, "org1", d, DisruptionStage.DIAGNOSED, actor_type="AGENT", actor="DIAGNOSIS")
    entries = session.query(AuditLogEntry).filter(AuditLogEntry.disruption_id == d.id).all()
    assert len(entries) == 1
    assert entries[0].action == "STAGE_CHANGED"
    assert entries[0].detail["to_stage"] == DisruptionStage.DIAGNOSED
