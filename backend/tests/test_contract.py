"""Hits every documented endpoint and asserts status 200 + basic schema shape.

Fixture IDs referenced here come from app/mocks/fixtures/*.json — see CONTRACT.md
for the full request/response reference.
"""

import uuid

import pytest

DISRUPTION_ID = "981f074f-9332-4b66-a24d-ffcaff0144cf"
DISRUPTION_ID_PENDING_APPROVAL = "6947d32f-c8f4-4cba-ac9b-398529becdb8"
VENDOR_ID = "4c34118b-bbe1-4016-885d-e6bc7917b3b0"
APPROVAL_ID = "9fa01c6e-d636-4009-ab03-c2d49ba11bc3"
NEGOTIATION_ID = "192864e3-7595-45fe-8a2b-16c4ce44aa27"
SETTLEMENT_BATCH_ID = "a7a105e1-2dc7-4ee8-b3b0-0eed03317722"
SKU = "CRS-2MM"


def test_agents_status(client):
    r = client.get("/api/v1/agents/status")
    assert r.status_code == 200
    body = r.json()
    assert len(body["agents"]) == 6
    assert {a["name"] for a in body["agents"]} == {
        "SENTINEL", "DIAGNOSIS", "SOURCING", "NEGOTIATION", "SETTLEMENT", "GOVERNANCE"
    }


def test_list_disruptions(client):
    r = client.get("/api/v1/disruptions")
    assert r.status_code == 200
    assert r.json()["total"] == 3

    r = client.get("/api/v1/disruptions", params={"stage": "DETECTED"})
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get("/api/v1/disruptions", params={"limit": 1})
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


def test_get_disruption(client):
    r = client.get(f"/api/v1/disruptions/{DISRUPTION_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == DISRUPTION_ID
    assert "exposure" in body and "breakdown" in body["exposure"]
    assert "diagnosis" in body
    assert "timeline" in body

    r = client.get("/api/v1/disruptions/does-not-exist")
    assert r.status_code == 404


def test_disruption_impact(client):
    r = client.get(f"/api/v1/disruptions/{DISRUPTION_ID}/impact")
    assert r.status_code == 200
    body = r.json()
    assert body["disruption_id"] == DISRUPTION_ID
    # VENDOR (layer 0) and PLANT (layer 2, fixed anchor) are always present;
    # ITEM/LINE/ORDER nodes depend on whether this vendor currently has any
    # open POs in the shared seeded DB, so don't assert on those directly.
    kinds = {n["kind"] for n in body["nodes"]}
    assert "VENDOR" in kinds
    assert "PLANT" in kinds
    node_ids = {n["id"] for n in body["nodes"]}
    for edge in body["edges"]:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
    layer_by_id = {n["id"]: n["layer"] for n in body["nodes"]}
    for edge in body["edges"]:
        assert layer_by_id[edge["source"]] < layer_by_id[edge["target"]]
    # summary must equal D1's actual latest exposure_calcs row, not a re-derived number
    disruption = client.get(f"/api/v1/disruptions/{DISRUPTION_ID}").json()
    assert body["summary"]["exposure_paise"] == disruption["exposure"]["total_paise"]
    # the fields the /command SummaryPanel renders
    assert body["summary"]["tier"] in ("CRITICAL", "ELEVATED", "MODERATE")
    assert body["summary"]["impacted_node_count"] == sum(1 for n in body["nodes"] if n["state"] == "IMPACTED")
    assert body["summary"]["at_risk_order_count"] == sum(1 for n in body["nodes"] if n["kind"] == "ORDER")

    r = client.get("/api/v1/disruptions/does-not-exist/impact")
    assert r.status_code == 404

    # cached: a second call returns the same computed_at (process-lifetime cache)
    r2 = client.get(f"/api/v1/disruptions/{DISRUPTION_ID}/impact")
    assert r2.json()["computed_at"] == body["computed_at"]


def test_list_vendors(client):
    # Phase 2 seeds 24 vendors (14 primary + 10 backup pool) — see app/seed.py —
    # so this checks shape/plausibility rather than a Phase-1-fixture-specific count.
    r = client.get("/api/v1/vendors")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] > 0
    assert body["total"] == len(body["items"])

    r = client.get("/api/v1/vendors", params={"search": "Pune"})
    assert r.status_code == 200
    search_body = r.json()
    assert search_body["total"] > 0
    assert all("pune" in (v["name"] + v["category"] + v["city"]).lower() for v in search_body["items"])


def test_get_vendor(client):
    r = client.get(f"/api/v1/vendors/{VENDOR_ID}")
    assert r.status_code == 200
    assert r.json()["id"] == VENDOR_ID


def test_vendor_dues(client):
    r = client.get("/api/v1/vendors/dues")
    assert r.status_code == 200
    body = r.json()
    assert body["total_due_paise"] > 0
    assert len(body["items"]) > 0
    assert body["total_due_paise"] == sum(i["total_due_paise"] for i in body["items"])


def test_vendor_context(client):
    r = client.get(f"/api/v1/vendors/{VENDOR_ID}/context")
    assert r.status_code == 200
    body = r.json()
    assert len(body["briefing"]) <= 300
    assert len(body["history_summary"]) <= 400
    assert body["memory_source"] in ("SUPERMEMORY", "DB_ONLY", "UNAVAILABLE")


def test_dashboard_summary(client):
    r = client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert "active_disruptions" in body
    assert "stage_counts" in body


def test_approval_decision_idempotent(client):
    key = str(uuid.uuid4())
    payload = {
        "decision": "APPROVE",
        "channel": "WEB",
        "decided_by": "test@sanjeevani.dev",
        "idempotency_key": key,
    }
    r1 = client.post(f"/api/v1/approvals/{APPROVAL_ID}/decision", json=payload)
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/approvals/{APPROVAL_ID}/decision", json=payload)
    assert r2.status_code == 200
    assert r1.json() == r2.json()
    assert r1.json()["new_stage"] == "APPROVED"


def test_approval_decision_unknown(client):
    r = client.post(
        "/api/v1/approvals/does-not-exist/decision",
        json={
            "decision": "APPROVE",
            "channel": "WEB",
            "decided_by": "test@sanjeevani.dev",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 404


def test_vendor_dues_endpoint_matches_dashboard(client):
    dues = client.get("/api/v1/vendors/dues").json()
    dashboard = client.get("/api/v1/dashboard/summary").json()
    assert dues["total_due_paise"] == dashboard["vendors_dues_total_paise"]


def test_settlements_execute(client):
    r = client.post(
        f"/api/v1/settlements/{SETTLEMENT_BATCH_ID}/execute",
        json={"idempotency_key": str(uuid.uuid4()), "executed_by": "finance.ops@sanjeevani.dev"},
    )
    assert r.status_code == 200
    assert r.json()["batch"]["status"] == "EXECUTING"


def test_settlement_batch_list(client):
    r = client.get("/api/v1/settlement/batch")
    assert r.status_code == 200
    assert r.json()["total"] == 2

    r = client.get("/api/v1/settlement/batch", params={"month": "2026-07"})
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_settlement_confirm(client):
    r = client.post(
        f"/api/v1/settlement/{SETTLEMENT_BATCH_ID}/confirm",
        json={"idempotency_key": str(uuid.uuid4()), "confirmed_by": "finance.ops@sanjeevani.dev"},
    )
    assert r.status_code == 200
    assert r.json()["batch"]["status"] == "CONFIRMED"


def test_audit_trail(client):
    r = client.get(f"/api/v1/audit/{DISRUPTION_ID}")
    assert r.status_code == 200
    assert len(r.json()["entries"]) > 0

    r = client.get("/api/v1/audit/does-not-exist")
    assert r.status_code == 404


def test_metrics_demo(client):
    r = client.get("/api/v1/metrics/demo")
    assert r.status_code == 200
    body = r.json()
    assert "latency" in body
    assert "integrations" in body
    valid_statuses = {"LIVE", "STUB", "UNAVAILABLE", "NOT_CONFIGURED"}
    assert all(v in valid_statuses for v in body["integrations"].values())


def test_forecast(client):
    r = client.get(f"/api/v1/forecast/{SKU}")
    assert r.status_code == 200
    body = r.json()
    assert body["sku"] == SKU
    assert len(body["history"]) > 0
    assert len(body["forecast"]) > 0

    r = client.get("/api/v1/forecast/NOT-A-SKU")
    assert r.status_code == 404


def test_negotiation_outcome(client):
    r = client.post(
        f"/api/v1/negotiations/{NEGOTIATION_ID}/outcome",
        json={
            "outcome": "AGREED",
            "final_unit_price_paise": 1400,
            "final_lead_time_days": 2,
            "final_payment_terms_days": 30,
            "transcript_summary": "Vendor agreed to revised pricing.",
            "idempotency_key": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["disruption_id"] == DISRUPTION_ID
    assert body["status"] == "AGREED"
    # D1 is seeded already resolved (SETTLEMENT_PENDING) — the Phase 4a state
    # machine (app.orchestrator.engine) correctly refuses to jump a disruption
    # backward to NEGOTIATED once it's already past that point, so re-posting
    # an outcome here is a no-op on stage, not a forced overwrite.
    assert body["new_stage"] == "SETTLEMENT_PENDING"


def test_live_ws_connect_and_replay(client):
    with client.websocket_connect("/api/v1/live") as ws:
        # Nothing has been broadcast yet in a fresh app instance, so the replay
        # buffer may be empty; the connection itself must succeed and stay open.
        ws.close()


# --- Demo phase D0: extended simulate + demo control plane -----------------

MARUDHAR_VENDOR_ID = "1f085369-1380-4c55-9cbc-f447ccd95df9"  # V4 — has an open PO history


def test_simulate_targets(client):
    r = client.get("/api/v1/simulate/targets")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    for item in body["items"]:
        assert {
            "vendor_id", "name", "category", "open_po_count",
            "downstream_line_count", "est_exposure_paise", "recommended_kinds",
        } <= item.keys()
        assert item["open_po_count"] > 0
    # sorted descending by estimated exposure
    exposures = [i["est_exposure_paise"] for i in body["items"]]
    assert exposures == sorted(exposures, reverse=True)


def test_simulate_missing_params(client):
    r = client.post("/api/v1/disruptions/simulate", json={})
    assert r.status_code == 422


def test_simulate_unknown_vendor(client):
    r = client.post(
        "/api/v1/disruptions/simulate",
        json={"vendor_id": "does-not-exist", "kind": "DELAYED"},
    )
    assert r.status_code == 404


def test_simulate_custom_vendor_kind(client):
    r1 = client.post(
        "/api/v1/disruptions/simulate",
        json={"vendor_id": MARUDHAR_VENDOR_ID, "kind": "BACKED_OUT", "effective_date": "2026-08-14"},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["scenario"] == "custom:BACKED_OUT"
    assert body1["stage"] in ("AWAITING_APPROVAL", "FAILED")

    # replaying against the same vendor+kind reports current stage rather
    # than re-raising a duplicate disruption.
    r2 = client.post(
        "/api/v1/disruptions/simulate",
        json={"vendor_id": MARUDHAR_VENDOR_ID, "kind": "BACKED_OUT"},
    )
    assert r2.status_code == 200
    assert r2.json()["disruption_id"] == body1["disruption_id"]
    assert r2.json()["newly_triggered"] is False


def test_simulate_scenario_backward_compatible(client):
    r = client.post("/api/v1/disruptions/simulate", json={"scenario": "delivery_delay_castings"})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario"] == "delivery_delay_castings"
    assert body["stage"] in ("AWAITING_APPROVAL", "FAILED")


def test_demo_state(client):
    r = client.get("/api/v1/demo/state")
    assert r.status_code == 200
    body = r.json()
    assert "disruption_count_by_stage" in body
    assert "integrations" in body
    assert isinstance(body["ttm_loaded"], bool)
    assert isinstance(body["ws_client_count"], int)
    assert "db_roundtrip_ms" in body


def test_demo_reset(client):
    r = client.post("/api/v1/demo/reset")
    assert r.status_code == 200
    body = r.json()
    assert body["reseeded_disruptions"] == 3
    for table in (
        "agent_runs", "audit_log", "vendor_candidates", "verifications",
        "negotiations", "approvals", "exposure_calcs", "disruption_events", "ws_ring_buffer",
    ):
        assert table in body["cleared"]

    # the three legacy golden-path disruptions are back, and the manual
    # trigger + stockout signals from earlier tests in this module are gone.
    r2 = client.get("/api/v1/disruptions")
    assert r2.status_code == 200
    assert r2.json()["total"] == 3


def test_phone_messages(client):
    """D4: Message thread from DB state (mock WhatsApp UI, no actual
    integration), in the flat items shape the /phone frontend renders."""
    r = client.get(f"/api/v1/phone/messages?disruption_id={DISRUPTION_ID}")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    items = body["items"]
    assert len(items) > 0
    # Messages should be sorted oldest first
    timestamps = [m["at"] for m in items]
    assert timestamps == sorted(timestamps)
    for msg in items:
        assert "id" in msg
        assert "at" in msg
        assert msg["from"] in ("AGENT", "OWNER")
        assert msg["kind"] in ("TEXT", "APPROVAL_CARD", "SYSTEM")
        if msg["kind"] == "APPROVAL_CARD":
            assert "disruption_id" in msg
            assert "approval_id" in msg
            assert "headline" in msg
            assert "exposure_display" in msg
            assert isinstance(msg.get("plan_summary"), list)
            assert "status" in msg


# --- Demo phase D5a/D5b: Agent sheet context and vendor correlation --------


def test_agent_vendor_sheet_csv(client):
    """D5a: GET /api/v1/agent/vendor-sheet.csv returns CSV of candidates or backup pool."""
    r = client.get("/api/v1/disruptions")
    assert r.status_code == 200
    disruptions = r.json()["items"]
    if not disruptions:
        pytest.skip("No disruptions seeded")

    disruption = disruptions[0]
    disruption_id = disruption["id"]

    # CSV for a specific disruption (should have candidates if sourced)
    r = client.get(f"/api/v1/agent/vendor-sheet.csv?disruption_id={disruption_id}")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    csv_content = r.text
    assert "vendor_id" in csv_content
    assert "vendor_name" in csv_content

    # CSV for no disruption (should return backup pool)
    r = client.get("/api/v1/agent/vendor-sheet.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers.get("content-type", "")
    csv_content = r.text
    assert "vendor_id" in csv_content


def _call_target_with_candidate(client):
    """/calls/start requires the vendor to be a sourcing candidate for the
    disruption — find a seeded disruption that has one."""
    r = client.get("/api/v1/disruptions")
    for summary in r.json()["items"]:
        detail = client.get(f"/api/v1/disruptions/{summary['id']}").json()
        if detail.get("candidates"):
            return detail["id"], detail["candidates"][0]["vendor_id"]
    return None, None


def test_call_session_lifecycle(client):
    """D5a/D5b: Call session creation and retrieval."""
    disruption_id, vendor_id = _call_target_with_candidate(client)
    if disruption_id is None:
        pytest.skip("No disruption with sourcing candidates seeded")

    # Start a call (LIVE mode so no background replay task fires in tests)
    r = client.post(
        "/api/v1/calls/start",
        json={
            "disruption_id": disruption_id,
            "vendor_id": vendor_id,
            "mode": "LIVE",
        },
    )
    assert r.status_code == 200
    call = r.json()
    assert call["status"] == "DIALING"
    assert call["vendor_id"] == vendor_id
    assert call["disruption_id"] == disruption_id
    # The frozen briefing + paise guardrails are what the call view renders.
    assert call["briefing_snapshot"].get("briefing")
    assert call["guardrails"].get("max_unit_price_paise")
    call_id = call["id"]

    # Retrieve the call
    r = client.get(f"/api/v1/calls/{call_id}")
    assert r.status_code == 200
    retrieved = r.json()
    assert retrieved["id"] == call_id
    assert retrieved["status"] == "DIALING"


def test_call_replay_with_bolna_webhook(client):
    """D5b: Replay call processes the captured Bolna payload end to end."""
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

    # Replay with fixture (processes webhook through the same pipeline)
    r = client.post(f"/api/v1/calls/{call_id}/replay")
    assert r.status_code == 200
    call = r.json()
    assert call["status"] == "ENDED"
    assert call["outcome_status"] == "completed"
    assert call["source"] == "REPLAY"
    assert len(call["transcript"]) > 0
    assert call["extracted"].get("unit_price") is not None
    fields = call["validation"]["fields"]
    assert fields["unit_price"]["valid"] is True
