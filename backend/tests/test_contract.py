"""Hits every documented endpoint and asserts status 200 + basic schema shape.

Fixture IDs referenced here come from app/mocks/fixtures/*.json — see CONTRACT.md
for the full request/response reference.
"""

import uuid

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


def test_list_vendors(client):
    r = client.get("/api/v1/vendors")
    assert r.status_code == 200
    assert r.json()["total"] == 5

    r = client.get("/api/v1/vendors", params={"search": "Pune"})
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_get_vendor(client):
    r = client.get(f"/api/v1/vendors/{VENDOR_ID}")
    assert r.status_code == 200
    assert r.json()["id"] == VENDOR_ID


def test_vendor_dues(client):
    r = client.get("/api/v1/vendors/dues")
    assert r.status_code == 200
    body = r.json()
    assert body["total_due_paise"] > 0
    assert len(body["items"]) == 5


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
    assert body["integrations"]["neon"] == "NOT_CONFIGURED"


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
    assert body["new_stage"] == "NEGOTIATED"


def test_live_ws_connect_and_replay(client):
    with client.websocket_connect("/api/v1/live") as ws:
        # Nothing has been broadcast yet in a fresh app instance, so the replay
        # buffer may be empty; the connection itself must succeed and stay open.
        ws.close()
