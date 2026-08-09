"""Guardian checkpoint #1: the Diagnosis agent's narrative must go through
groundedness checking, and a persistent failure must fall back to a
template-generated narrative rather than publish an ungrounded claim. All
against StubLLM/a monkeypatched Guardian — no network.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentContext
from app.agents.diagnosis import DiagnosisAgent
from app.db.base import Base
from app.db.models import DisruptionEvent, Organisation, PurchaseOrder, Vendor
from app.llm.guardian import GuardianMode, GuardianVerdict
from app.llm.runs import NullAgentRunRecorder
from app.schemas.money import utc_now


@pytest.fixture()
def session(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "stub")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()

    now = utc_now()
    s.add(Organisation(id="org1", name="T", city="Pune", industry="x", revenue_cr=1.0, lat=1.0, lng=1.0, created_at=now))
    s.add(Vendor(
        id="v1", org_id="org1", name="Bharat Casting Industries", category="Castings", gstin="27AABCS1429B1ZP",
        udyam_number=None, phone="+91", email="a@b.com", city="Rajkot", state="Gujarat",
        lat=22.3, lng=70.8, languages=[], reliability_score=70, on_time_rate=0.8, orders_completed=20,
        disputes=1, avg_lead_time_days=4.0, is_backup_pool=False, payment_terms_days=30,
        created_at=now, updated_at=now,
    ))
    s.add(PurchaseOrder(
        id="po1", org_id="org1", vendor_id="v1", po_number="PO-1", item_sku="CST-1", item_name="Bracket",
        qty=1200, unit_price_paise=42_000, ordered_at=now, promised_at=now, delivered_at=None, status="LATE",
        downstream_order_ref="SO-1", downstream_order_value_paise=1_300_000_000, penalty_rate_bps=125,
    ))
    s.add(DisruptionEvent(
        id="d1", org_id="org1", type="DELIVERY_DELAY", stage="DETECTED", vendor_id="v1", detected_at=now,
        headline="Bharat Casting Industries 4 days overdue", signal_payload={"days_late": 4},
        detector_name="overdue_delivery", detector_source="RULE_BASED", affected_po_ids=["po1"],
    ))
    s.flush()
    yield s
    s.close()


def _run_diagnosis(session) -> DisruptionEvent:
    DiagnosisAgent(recorder=NullAgentRunRecorder()).run(AgentContext(session=session, org_id="org1", disruption_id="d1"))
    return session.get(DisruptionEvent, "d1")


class _FakeGuardian:
    """Returns a scripted sequence of verdicts, one per call — lets us drive
    the exact fail-once / fail-twice paths deterministically."""

    def __init__(self, *verdicts: GuardianVerdict):
        self._verdicts = list(verdicts)
        self.calls = 0

    def check(self, *args, **kwargs) -> GuardianVerdict:
        verdict = self._verdicts[min(self.calls, len(self._verdicts) - 1)]
        self.calls += 1
        return verdict


def _verdict(passed: bool, status: str = "OK") -> GuardianVerdict:
    return GuardianVerdict(
        passed=passed, risk=None, raw_label="Yes" if not passed else "No", confidence=0.8,
        model_id="stub-guardian", latency_ms=1.0, status=status, mode=GuardianMode.LLM_SURROGATE,
    )


def test_groundedness_pass_on_first_try_uses_llm_narrative(session, monkeypatch):
    fake = _FakeGuardian(_verdict(passed=True))
    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: fake)

    disruption = _run_diagnosis(session)

    assert fake.calls == 1
    assert disruption.diagnosis_narrative_source == "LLM"
    assert disruption.diagnosis_guardian_status == "PASSED"


def test_fails_once_then_regenerates_and_passes(session, monkeypatch):
    fake = _FakeGuardian(_verdict(passed=False), _verdict(passed=True))
    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: fake)

    disruption = _run_diagnosis(session)

    assert fake.calls == 2, "should check once, regenerate, then check again"
    assert disruption.diagnosis_narrative_source == "LLM"
    assert disruption.diagnosis_guardian_status == "PASSED"


def test_fails_twice_falls_back_to_template(session, monkeypatch):
    fake = _FakeGuardian(_verdict(passed=False), _verdict(passed=False))
    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: fake)

    disruption = _run_diagnosis(session)

    assert fake.calls == 2, "must not retry a third time"
    assert disruption.diagnosis_narrative_source == "TEMPLATE"
    assert disruption.diagnosis_guardian_status == "FAILED"
    assert disruption.diagnosis_guardian_passed is False
    # the template narrative is built from data Python already computed, so it
    # must still be non-empty and reference the root cause / exposure.
    assert disruption.diagnosis_narrative
    assert len(disruption.diagnosis_narrative) <= 280


def test_guardian_unavailable_does_not_force_template_fallback(session, monkeypatch):
    """UNAVAILABLE (status != OK) must not trigger the regenerate/template
    path — that's reserved for a real, checked groundedness failure. See
    app.llm.guardian's module docstring on UNAVAILABLE semantics."""
    fake = _FakeGuardian(_verdict(passed=True, status="UNAVAILABLE"))
    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: fake)

    disruption = _run_diagnosis(session)

    assert fake.calls == 1
    assert disruption.diagnosis_narrative_source == "LLM"
    assert disruption.diagnosis_guardian_status == "UNAVAILABLE"
    assert disruption.diagnosis_guardian_passed is True


def test_exposure_calc_row_is_persisted_alongside_diagnosis(session, monkeypatch):
    from app.db.models import ExposureCalc

    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: _FakeGuardian(_verdict(passed=True)))
    _run_diagnosis(session)

    calc = session.query(ExposureCalc).filter(ExposureCalc.disruption_id == "d1").one()
    # Hand-calculated: blocked = 1200*42000 = 50,400,000; penalty = 1_300_000_000*125//10000 = 16,250,000
    assert calc.total_paise == 50_400_000 + 16_250_000 == 66_650_000
    assert calc.formula_version == "v1"


def test_diagnosis_result_ok(session, monkeypatch):
    monkeypatch.setattr("app.agents.diagnosis.get_guardian", lambda: _FakeGuardian(_verdict(passed=True)))
    result = DiagnosisAgent(recorder=NullAgentRunRecorder()).run(
        AgentContext(session=session, org_id="org1", disruption_id="d1")
    )
    assert result.ok
    assert result.data["total_paise"] == 66_650_000
