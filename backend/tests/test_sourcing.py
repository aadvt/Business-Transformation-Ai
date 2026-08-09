"""Sourcing agent tests: the deterministic scoring is exercised directly
(pure function, no DB), and a full agent run is exercised against an
in-memory sqlite DB with StubLLM — no network anywhere in this file.
"""

from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext
from app.agents.sourcing import SourcingAgent, _candidate_avg_price, _clamp01, _haversine_km, _score_candidate
from app.config import settings
from app.db.base import Base
from app.db.models import DisruptionEvent, Organisation, PurchaseOrder, Vendor
from app.llm.runs import NullAgentRunRecorder
from app.schemas.money import utc_now


def _vendor(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="v1", name="Test Vendor", category="Castings", reliability_score=80,
        avg_lead_time_days=3.0, lat=18.5204, lng=73.8567, orders_completed=10,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --- pure scoring: haversine ---------------------------------------------------


def test_haversine_zero_for_same_point():
    assert _haversine_km(18.5, 73.8, 18.5, 73.8) == pytest.approx(0.0, abs=1e-6)


def test_haversine_pune_to_chennai_is_plausible():
    # Pune (18.5204, 73.8567) to Chennai (13.0827, 80.2707) is ~830km by air.
    distance = _haversine_km(18.5204, 73.8567, 13.0827, 80.2707)
    assert 700 < distance < 950


def test_clamp01_bounds():
    assert _clamp01(-5) == 0.0
    assert _clamp01(5) == 1.0
    assert _clamp01(0.5) == 0.5


# --- pure scoring: _score_candidate --------------------------------------------


def test_score_candidate_is_deterministic():
    v = _vendor()
    s1 = _score_candidate(v, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    s2 = _score_candidate(v, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    assert s1 == s2


def test_higher_reliability_scores_higher():
    weak = _vendor(reliability_score=40)
    strong = _vendor(reliability_score=95)
    weak_score = _score_candidate(weak, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    strong_score = _score_candidate(strong, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    assert strong_score.match_score > weak_score.match_score
    assert strong_score.reliability_component > weak_score.reliability_component


def test_shorter_lead_time_scores_higher():
    slow = _vendor(avg_lead_time_days=settings.max_lead_time_days - 1)
    fast = _vendor(avg_lead_time_days=1.0)
    slow_score = _score_candidate(slow, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    fast_score = _score_candidate(fast, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    assert fast_score.lead_time_component > slow_score.lead_time_component


def test_price_at_reference_scores_higher_than_far_from_reference():
    at_reference = _score_candidate(_vendor(), reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    far_from_reference = _score_candidate(_vendor(), reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=50_000)
    assert at_reference.price_component > far_from_reference.price_component
    assert at_reference.price_component == 1.0


def test_closer_vendor_scores_higher_geography():
    near = _vendor(lat=18.53, lng=73.86)  # a few km from the plant
    far = _vendor(lat=13.0827, lng=80.2707)  # Chennai
    near_score = _score_candidate(near, reference_price_paise=10_000, plant_lat=18.5204, plant_lng=73.8567, candidate_avg_price_paise=10_000)
    far_score = _score_candidate(far, reference_price_paise=10_000, plant_lat=18.5204, plant_lng=73.8567, candidate_avg_price_paise=10_000)
    assert near_score.geography_component > far_score.geography_component


def test_relationship_component_is_binary():
    new_vendor = _vendor(orders_completed=0)
    returning_vendor = _vendor(orders_completed=1)
    assert _score_candidate(new_vendor, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000).relationship_component == 0.0
    assert _score_candidate(returning_vendor, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000).relationship_component == 1.0


def test_zero_reference_price_falls_back_to_neutral_price_component():
    score = _score_candidate(_vendor(), reference_price_paise=0.0, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
    assert score.price_component == 0.5


def test_scoring_weights_sum_to_one():
    total = (
        settings.sourcing_weight_reliability + settings.sourcing_weight_lead_time
        + settings.sourcing_weight_price + settings.sourcing_weight_geography
        + settings.sourcing_weight_relationship
    )
    assert total == pytest.approx(1.0)


def test_ordering_is_stable_across_repeated_scoring():
    """Same inputs, scored and sorted twice independently, must produce the
    identical vendor order — no hidden nondeterminism (e.g. dict/set ordering)."""
    candidates = [_vendor(id=f"v{i}", name=f"Vendor {i}", reliability_score=50 + i * 7) for i in range(5)]

    def rank_once():
        scores = [
            _score_candidate(v, reference_price_paise=10_000, plant_lat=18.5, plant_lng=73.8, candidate_avg_price_paise=10_000)
            for v in candidates
        ]
        scores.sort(key=lambda s: (-s.match_score, s.vendor_name))
        return [s.vendor_id for s in scores]

    order1 = rank_once()
    order2 = rank_once()
    assert order1 == order2
    # Higher reliability_score with everything else equal must rank first.
    assert order1[0] == "v4"


# --- full agent run against in-memory sqlite, StubLLM ---------------------------


@pytest.fixture()
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _seed_minimal_sourcing_scenario(session):
    now = utc_now()
    session.add(Organisation(id="org1", name="T", city="Pune", industry="x", revenue_cr=1.0, lat=18.5204, lng=73.8567, created_at=now))

    failed_vendor = Vendor(
        id="failed", org_id="org1", name="Failed Vendor", category="Castings", gstin="27AABCS1429B1ZP",
        udyam_number=None, phone="+91", email="a@b.com", city="Pune", state="Maharashtra",
        lat=18.5, lng=73.8, languages=[], reliability_score=50, on_time_rate=0.6, orders_completed=10,
        disputes=1, avg_lead_time_days=5.0, is_backup_pool=False, payment_terms_days=30,
        created_at=now, updated_at=now,
    )
    session.add(failed_vendor)

    for i in range(3):
        session.add(Vendor(
            id=f"cand{i}", org_id="org1", name=f"Candidate {i}", category="Castings", gstin="27AABCS1429B1ZP",
            udyam_number=None, phone="+91", email="a@b.com", city="Pune", state="Maharashtra",
            lat=18.5 + i * 0.01, lng=73.8, languages=[], reliability_score=60 + i * 10, on_time_rate=0.8,
            orders_completed=5, disputes=0, avg_lead_time_days=2.0 + i, is_backup_pool=(i > 0),
            payment_terms_days=30, created_at=now, updated_at=now,
        ))

    session.add(PurchaseOrder(
        id="po1", org_id="org1", vendor_id="failed", po_number="PO-1", item_sku="CST-1", item_name="Bracket",
        qty=100, unit_price_paise=10_000, ordered_at=now, promised_at=now, delivered_at=None, status="LATE",
        downstream_order_ref=None, downstream_order_value_paise=None, penalty_rate_bps=None,
    ))
    session.add(DisruptionEvent(
        id="d1", org_id="org1", type="DELIVERY_DELAY", stage="DIAGNOSED", vendor_id="failed", detected_at=now,
        headline="Test", signal_payload={}, detector_name="overdue_delivery", detector_source="RULE_BASED",
        affected_po_ids=["po1"],
    ))
    session.flush()


def test_sourcing_agent_persists_top_candidates(db_session, monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "stub")
    _seed_minimal_sourcing_scenario(db_session)

    from app.db.models import VendorCandidate

    agent = SourcingAgent(recorder=NullAgentRunRecorder())
    result = agent.run(AgentContext(session=db_session, org_id="org1", disruption_id="d1"))

    assert result.ok
    candidates = db_session.query(VendorCandidate).filter(VendorCandidate.disruption_id == "d1").all()
    assert len(candidates) == 3
    assert result.data["candidate_count"] == 3


def test_sourcing_agent_ranks_deterministically_across_two_fresh_runs(monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import VendorCandidate

    monkeypatch.setattr("app.config.settings.llm_provider", "stub")

    def run_once():
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()
        _seed_minimal_sourcing_scenario(session)
        SourcingAgent(recorder=NullAgentRunRecorder()).run(AgentContext(session=session, org_id="org1", disruption_id="d1"))
        rows = session.execute(
            select(VendorCandidate).where(VendorCandidate.disruption_id == "d1").order_by(VendorCandidate.rank)
        ).scalars().all()
        order = [(r.vendor_id, r.rank, r.match_score) for r in rows]
        session.close()
        return order

    assert run_once() == run_once()


def test_candidate_avg_price_none_when_vendor_has_no_purchase_orders(db_session):
    db_session.add(Organisation(id="org1", name="T", city="Pune", industry="x", revenue_cr=1.0, lat=1.0, lng=1.0, created_at=utc_now()))
    db_session.add(Vendor(
        id="v1", org_id="org1", name="No History", category="X", gstin="27AABCS1429B1ZP", udyam_number=None,
        phone="+91", email="a@b.com", city="Pune", state="Maharashtra", lat=1.0, lng=1.0, languages=[],
        reliability_score=50, on_time_rate=0.5, orders_completed=0, disputes=0, avg_lead_time_days=5.0,
        is_backup_pool=True, payment_terms_days=30, created_at=utc_now(), updated_at=utc_now(),
    ))
    db_session.flush()
    assert _candidate_avg_price(db_session, "v1") is None
