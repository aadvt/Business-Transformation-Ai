"""D5b: Vendor correlation via resolve_vendor() — webhook payload matching.

Tests the correlation ladder: exact vendor_id extraction > normalized phone matching
> newest pending negotiation session. Verifies CallSession creation and correlation_method
tracking when Bolna webhooks arrive.
"""

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import DEFAULT_ORG_ID
from app.db.models import CallSession, DisruptionEvent, Negotiation, Vendor
from app.db.session import SessionLocal
from app.services.agent_sheet import resolve_vendor, _norm_phone


class TestPhoneNormalization:
    """_norm_phone() handles country codes, leading 0, and formatting."""

    def test_standard_10_digit(self):
        """10-digit Indian number stays as-is."""
        assert _norm_phone("9876543210") == "9876543210"

    def test_with_country_code_91(self):
        """Country code +91 is stripped."""
        assert _norm_phone("+919876543210") == "9876543210"
        assert _norm_phone("919876543210") == "9876543210"

    def test_with_leading_zero(self):
        """Leading 0 (landline) is stripped."""
        assert _norm_phone("09876543210") == "9876543210"

    def test_with_dashes(self):
        """Dashes are stripped, last 10 digits extracted."""
        assert _norm_phone("98-765-43210") == "9876543210"
        assert _norm_phone("+91-9876-543210") == "9876543210"

    def test_with_spaces(self):
        """Spaces are stripped."""
        assert _norm_phone("9876 543 210") == "9876543210"

    def test_country_code_and_leading_zero_handling(self):
        """91 prefix AND leading 0 scenario (e.g., 9109876543210)."""
        # Strip 91, then if next digit is 0, strip that too
        assert _norm_phone("9109876543210") == "9876543210"

    def test_bolna_payload_format(self):
        """Real Bolna format from bolna_replay.json."""
        assert _norm_phone("+916360463302") == "6360463302"

    def test_none_input(self):
        """None returns empty, then -10 slice returns empty."""
        assert _norm_phone(None) == ""

    def test_empty_string(self):
        """Empty string returns empty."""
        assert _norm_phone("") == ""


class TestResolveVendorCorrelationLadder:
    """resolve_vendor() tries vendor_id > phone > pending negotiation > none."""

    @pytest.fixture(scope="function")
    def session(self):
        """Fresh session per test."""
        s = SessionLocal()
        yield s
        s.close()

    def test_vendor_id_extraction_tier_1(self, session: Session):
        """Exact vendor_id in extracted data takes priority."""
        # Get a real vendor from DB
        vendor = session.execute(select(Vendor).limit(1)).scalars().first()
        assert vendor is not None

        extracted = {"vendor_id": vendor.id}
        resolved, method = resolve_vendor(session, extracted, phone="0000000000")
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "vendor_id"

    def test_phone_matching_tier_2(self, session: Session):
        """Phone normalization fallback when vendor_id not present."""
        # Get a real vendor and use their phone
        vendor = session.execute(select(Vendor).limit(1)).scalars().first()
        assert vendor is not None
        vendor_phone = vendor.phone

        # Call with phone only (no vendor_id)
        resolved, method = resolve_vendor(session, {}, phone=vendor_phone)
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "phone"

    def test_phone_matching_with_normalization(self, session: Session):
        """Phone normalization handles country codes and formatting."""
        vendor = session.execute(select(Vendor).limit(1)).scalars().first()
        assert vendor is not None
        vendor_phone = vendor.phone

        # Bolna format: +91 prefix on the normalized 10 digits (the raw phone
        # string may contain spaces/dashes, so slicing it directly is wrong)
        bolna_format = f"+91{_norm_phone(vendor_phone)}"
        resolved, method = resolve_vendor(session, {}, phone=bolna_format)
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "phone"

    def test_pending_negotiation_tier_3(self, session: Session):
        """Fallback to newest pending negotiation when phone/vendor_id not found."""
        # Create a pending negotiation
        disruption = session.execute(
            select(DisruptionEvent).filter(DisruptionEvent.stage != "FAILED").limit(1)
        ).scalars().first()
        if not disruption:
            pytest.skip("No suitable disruption for pending negotiation test")

        vendor = session.get(Vendor, disruption.vendor_id)
        assert vendor is not None

        # Create a PENDING negotiation
        pending = Negotiation(
            id="pending-test-neg",
            disruption_id=disruption.id,
            vendor_id=vendor.id,
            status="IN_PROGRESS",
            started_at=datetime.now(timezone.utc),
        )
        session.add(pending)
        session.flush()

        # No vendor_id or phone in extracted data
        resolved, method = resolve_vendor(session, {}, phone="9999999999")
        # Should resolve to pending negotiation vendor
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "pending_session"

        session.rollback()

    def test_no_match_returns_none(self, session: Session):
        """Returns (None, 'none') when no correlation possible."""
        # Use a phone that doesn't match any vendor
        resolved, method = resolve_vendor(session, {}, phone="1234567890")
        assert resolved is None
        assert method == "none"

    def test_extracted_phone_fallback(self, session: Session):
        """Extracted dict can contain phone field."""
        vendor = session.execute(select(Vendor).limit(1)).scalars().first()
        assert vendor is not None

        extracted = {"phone": vendor.phone}
        resolved, method = resolve_vendor(session, extracted, phone=None)
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "phone"

    def test_extracted_callee_phone_fallback(self, session: Session):
        """Extracted dict can contain callee_phone field."""
        vendor = session.execute(select(Vendor).limit(1)).scalars().first()
        assert vendor is not None

        extracted = {"callee_phone": vendor.phone}
        resolved, method = resolve_vendor(session, extracted, phone=None)
        assert resolved is not None
        assert resolved.id == vendor.id
        assert method == "phone"


def _call_target_with_candidate(client):
    """/calls/start requires the vendor to be a sourcing candidate for the
    disruption — find a seeded disruption that has one."""
    r = client.get("/api/v1/disruptions")
    for summary in r.json()["items"]:
        detail = client.get(f"/api/v1/disruptions/{summary['id']}").json()
        if detail.get("candidates"):
            return detail["id"], detail["candidates"][0]["vendor_id"]
    return None, None


class TestWebhookCallSessionCreation:
    """Webhook integration creates CallSession with correlation_method."""

    def test_webhook_endpoint_exists(self, client):
        """POST /api/v1/webhooks/bolna endpoint accessible (though requires auth)."""
        # Without proper secret header, should get 401
        r = client.post(
            "/api/v1/webhooks/bolna",
            json={"id": "test", "user_number": "+919876543210"},
            headers={"X-Voice-Adapter-Secret": "wrong-secret"},
        )
        assert r.status_code == 401

    def test_calls_start_endpoint(self, client):
        """POST /api/v1/calls/start creates a CallSession."""
        disruption_id, vendor_id = _call_target_with_candidate(client)
        if disruption_id is None:
            pytest.skip("No disruption with sourcing candidates seeded")

        r = client.post(
            "/api/v1/calls/start",
            json={
                "disruption_id": disruption_id,
                "vendor_id": vendor_id,
                "mode": "LIVE",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "DIALING"
        assert body["vendor_id"] == vendor_id
        assert body["disruption_id"] == disruption_id
        assert "id" in body

    def test_get_call_session(self, client):
        """GET /api/v1/calls/{call_id} retrieves CallSession."""
        disruption_id, vendor_id = _call_target_with_candidate(client)
        if disruption_id is None:
            pytest.skip("No disruption with sourcing candidates seeded")

        r = client.post(
            "/api/v1/calls/start",
            json={
                "disruption_id": disruption_id,
                "vendor_id": vendor_id,
                "mode": "LIVE",
            },
        )
        assert r.status_code == 200
        call_id = r.json()["id"]

        # Retrieve it
        r = client.get(f"/api/v1/calls/{call_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == call_id
        assert body["disruption_id"] == disruption_id

    def test_replay_call_processes_webhook(self, client):
        """POST /api/v1/calls/{call_id}/replay processes Bolna transcript."""
        disruption_id, vendor_id = _call_target_with_candidate(client)
        if disruption_id is None:
            pytest.skip("No disruption with sourcing candidates seeded")

        r = client.post(
            "/api/v1/calls/start",
            json={
                "disruption_id": disruption_id,
                "vendor_id": vendor_id,
                "mode": "LIVE",
            },
        )
        call_id = r.json()["id"]

        # Replay with bolna_replay.json fixture
        r = client.post(f"/api/v1/calls/{call_id}/replay")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ENDED"
        assert len(body["transcript"]) > 0
        assert body["extracted"].get("unit_price") is not None


class TestCorrelationMethodTracking:
    """correlation_method field is correctly populated on CallSession."""

    def test_correlation_method_stored(self):
        """correlation_method is persisted to DB."""
        with SessionLocal() as session:
            # Get a vendor and create a CallSession with a specific correlation method
            vendor = session.execute(select(Vendor).limit(1)).scalars().first()
            assert vendor is not None

            from app.schemas.money import utc_now

            call = CallSession(
                id="test-call-correlation",
                vendor_id=vendor.id,
                status="ENDED",
                source="LIVE_BOLNA",
                started_at=utc_now(),
                phone=vendor.phone,
                correlation_method="phone",
            )
            session.add(call)
            session.flush()
            session.commit()

            # Retrieve and verify
            retrieved = session.get(CallSession, "test-call-correlation")
            assert retrieved is not None
            assert retrieved.correlation_method == "phone"
            assert retrieved.vendor_id == vendor.id

            session.delete(retrieved)
            session.commit()

    def test_correlation_method_precedence(self):
        """Test that vendor_id > phone > pending_session precedence is maintained."""
        with SessionLocal() as session:
            vendor1 = session.execute(select(Vendor).limit(1)).scalars().first()
            vendor2 = (
                session.execute(select(Vendor).offset(1).limit(1)).scalars().first()
            )
            assert vendor1 is not None
            assert vendor2 is not None

            # Case 1: vendor_id provided → method is vendor_id
            extracted = {"vendor_id": vendor1.id}
            resolved, method = resolve_vendor(session, extracted, phone=vendor2.phone)
            assert resolved.id == vendor1.id
            assert method == "vendor_id"

            # Case 2: no vendor_id, but phone matches → method is phone
            extracted = {}
            resolved, method = resolve_vendor(session, extracted, phone=vendor2.phone)
            assert resolved.id == vendor2.id
            assert method == "phone"
