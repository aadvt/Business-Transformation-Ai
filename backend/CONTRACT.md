# Sanjeevani Backend — API Contract

**This document is unchanged since Phase 1.** Phase 2 swapped the data source
(JSON fixtures → Neon Postgres, `USE_MOCKS=true` keeps the old fixture path as
a fallback) but every endpoint, request/response shape, and status code below
is identical — that was the explicit constraint. Example payloads below now
reflect real seeded data (see `app/seed.py`) rather than static fixtures.

Base URL (dev): `http://localhost:8000`
All routes are versioned under `/api/v1`. Auth: optional `X-API-Key` header (see
README — off by default in dev). Full interactive docs at `/docs`.

**Conventions** (see `CLAUDE.md` for the source of truth):
- Money → integer paise, fields suffixed `_paise`, always paired with a
  human-readable `_display` string (e.g. `total_paise` / `total_display`).
- Timestamps → UTC ISO-8601, fields suffixed `_at`.
- IDs → string UUIDv4.
- Every domain object includes `id`, `created_at`, `updated_at`.

---

## Frontend-facing endpoints

### `GET /api/v1/agents/status`

Returns the current status of every agent.

```json
{
  "agents": [
    {
      "name": "SENTINEL",
      "status": "RUNNING",
      "current_task": "Scanning carrier telemetry + TTM forecast feeds",
      "last_updated_at": "2026-08-09T06:00:00+00:00",
      "disruption_id": null
    }
  ]
}
```

`name` ∈ `SENTINEL | DIAGNOSIS | SOURCING | NEGOTIATION | SETTLEMENT | GOVERNANCE`
`status` ∈ `IDLE | RUNNING | DONE | BLOCKED | ERROR`

---

### `GET /api/v1/disruptions?stage=&limit=`

List disruptions, most recent first. Both query params optional.
- `stage`: filter to one `DisruptionStage` value.
- `limit`: default 50, max 200.

```json
{
  "items": [
    {
      "id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
      "type": "DELIVERY_DELAY",
      "stage": "SETTLEMENT_PENDING",
      "detected_at": "2026-08-07T03:12:00+00:00",
      "vendor": { "id": "4c34118b-...", "name": "Shree Balaji Auto Components", "gstin": "27AABCS1429B1ZP" },
      "headline": "M8 hex bolt shipment 6 days behind schedule, line stoppage risk at Chakan plant",
      "exposure_total_paise": 1850000000,
      "exposure_total_display": "₹1,85,00,000",
      "detector_source": "RULE_BASED"
    }
  ],
  "total": 1
}
```

---

### `GET /api/v1/disruptions/{id}`

Full disruption detail — the richest object in the system. 404 if not found.

```json
{
  "id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "type": "DELIVERY_DELAY",
  "stage": "SETTLEMENT_PENDING",
  "detected_at": "2026-08-07T03:12:00+00:00",
  "vendor": { "id": "4c34118b-...", "name": "Shree Balaji Auto Components", "gstin": "27AABCS1429B1ZP" },
  "affected_po_ids": ["3dd81f7b-...", "2c7c0476-..."],
  "headline": "M8 hex bolt shipment 6 days behind schedule, line stoppage risk at Chakan plant",
  "exposure": {
    "total_paise": 1850000000,
    "total_display": "₹1,85,00,000",
    "confidence": 0.87,
    "breakdown": [
      {
        "label": "Idle assembly line cost",
        "amount_paise": 1200000000,
        "amount_display": "₹1,20,00,000",
        "basis": "6 days of Chakan line-3 downtime at historical ₹20L/day idle cost"
      }
    ]
  },
  "diagnosis": {
    "root_cause": "TRANSPORT_BREAKDOWN",
    "narrative": "Carrier's truck suffered an axle failure on NH48 near Lonavala...",
    "evidence": ["GPS ping gap of 14 hours on carrier tracking API"],
    "guardian": { "status": "PASSED", "passed": true }
  },
  "candidates": [
    {
      "vendor_id": "1799a38c-...",
      "name": "Kohinoor Precision Pvt Ltd",
      "match_score": 0.88,
      "verification": {
        "status": "VERIFIED",
        "gstin_status": "VERIFIED",
        "udyam_status": "VERIFIED",
        "checked_at": "2026-08-07T03:40:00+00:00",
        "source": "GST_PORTAL_STUB"
      },
      "quoted_lead_time_days": 2,
      "quoted_unit_price_paise": 1450
    }
  ],
  "approval": {
    "id": "a52a6e18-...",
    "status": "APPROVED",
    "requested_at": "2026-08-07T04:00:00+00:00",
    "decided_at": "2026-08-07T04:22:00+00:00",
    "decided_by": "priya.sharma@mahe-industries.in",
    "channel": "WEB"
  },
  "negotiation": {
    "id": "192864e3-...",
    "vendor_id": "1799a38c-...",
    "status": "AGREED",
    "opening_terms": { "unit_price_paise": 1600, "lead_time_days": 3, "payment_terms_days": 30 },
    "final_terms": { "unit_price_paise": 1450, "lead_time_days": 2, "payment_terms_days": 30 },
    "rounds": 3,
    "transcript_summary": "Vendor agreed to expedite to 2-day lead time...",
    "guardian": { "status": "PASSED", "passed": true }
  },
  "timeline": [
    { "stage": "DETECTED", "at": "2026-08-07T03:12:00+00:00", "agent": "SENTINEL", "note": "Delivery delay signal raised" }
  ],
  "detector_source": "RULE_BASED"
}
```

`stage` ∈ `DETECTED | DIAGNOSED | SOURCING | AWAITING_APPROVAL | APPROVED | REJECTED | NEGOTIATING | NEGOTIATED | SETTLEMENT_PENDING | SETTLED | CLOSED | FAILED`
`type` ∈ `DELIVERY_DELAY | VENDOR_UNRESPONSIVE | QUALITY_REJECTION | STOCKOUT_RISK | PRICE_SHOCK | LOGISTICS_HOLD`
`detector_source` ∈ `RULE_BASED | TTM_FORECAST` — which mechanism raised the signal.
`approval` and `negotiation` are `null` until that stage is reached.

---

### `GET /api/v1/disruptions/{id}/impact` (Demo phase D1)

The disruption's blast radius as a layered node/edge graph for the frontend
to render and animate. 404 if the disruption doesn't exist. Deterministic —
no LLM involved (see `app/services/impact.py`); the `summary` block is the
disruption's own latest `exposure_calcs` row, never a second, independently
computed number.

```json
{
  "disruption_id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "nodes": [
    {
      "id": "vendor:4c34118b-bbe1-4016-885d-e6bc7917b3b0",
      "kind": "VENDOR", "layer": 0, "label": "Shree Balaji Auto Components",
      "state": "IMPACTED", "badges": ["2 open POs", "on-time 91%"]
    },
    {
      "id": "item:M8-HEX-BOLT",
      "kind": "ITEM", "layer": 1, "label": "M8 hex bolt (M8-HEX-BOLT)",
      "state": "IMPACTED", "badges": ["1,200 units short"]
    },
    {
      "id": "line:aggregate",
      "kind": "LINE", "layer": 2, "label": "Fasteners production line",
      "state": "IMPACTED", "badges": ["1 SKUs affected"]
    },
    {
      "id": "plant:b2f6c8a0-0000-4000-8000-000000000001",
      "kind": "PLANT", "layer": 2, "label": "Shakti Auto Components Pvt Ltd",
      "state": "AT_RISK", "badges": []
    },
    {
      "id": "order:3dd81f7b-...",
      "kind": "ORDER", "layer": 3, "label": "SO-2026-0842",
      "state": "IMPACTED", "badges": ["₹20.0L at risk", "SLA penalty"]
    }
  ],
  "edges": [
    { "id": "edge:vendor:4c34118b-...->item:M8-HEX-BOLT", "source": "vendor:4c34118b-...", "target": "item:M8-HEX-BOLT", "state": "IMPACTED" },
    { "id": "edge:item:M8-HEX-BOLT->line:aggregate", "source": "item:M8-HEX-BOLT", "target": "line:aggregate", "state": "IMPACTED" },
    { "id": "edge:item:M8-HEX-BOLT->order:3dd81f7b-...", "source": "item:M8-HEX-BOLT", "target": "order:3dd81f7b-...", "state": "IMPACTED" }
  ],
  "summary": {
    "exposure_total_paise": 1850000000,
    "exposure_total_display": "₹1,85,00,000",
    "exposure_confidence": 0.87,
    "exposure_calc_id": "c1a2...-uuid",
    "severity_tier": 1,
    "tier_thresholds_paise": { "tier_1_paise": 100000000, "tier_2_paise": 30000000 }
  },
  "computed_at": "2026-08-09T06:00:00+00:00"
}
```

Layers, left to right: `0 VENDOR` (the disrupted vendor) → `1 ITEM` (distinct
SKUs from the vendor's open POs) → `2 LINE` (production line(s) consuming a
production-critical SKU) and a fixed `2 PLANT` anchor (the org — always
present, but has no edges of its own; it's a layout landmark, not a
propagation step) → `3 ORDER` (downstream orders, i.e. open POs carrying a
`downstream_order_ref`, reached from the affected items). Every edge strictly
increases layer (except the PLANT anchor, which has none). `kind` ∈
`VENDOR | ITEM | LINE | ORDER | PLANT` (`GraphNodeKind`); `state` ∈
`HEALTHY | AT_RISK | IMPACTED | SUBSTITUTED` (`GraphNodeState`) — an edge
always carries the same state as its downstream node. `severity_tier`: `1`
if `exposure_total_paise >= tier_1_paise`, `2` if `>= tier_2_paise`, else
`3` — thresholds are echoed back in the response so the UI can show why.

Cached in-process for the life of the server, keyed on the disruption's own
freshness (its latest per-stage timestamp plus its latest `exposure_calcs`
row's `computed_at`, since a new exposure row — e.g. once Sourcing prices a
backup quote — is what actually changes the graph's content between calls).

---

### `GET /api/v1/vendors?search=&limit=`

`search` matches against name, category, or city (case-insensitive substring).

```json
{
  "items": [
    {
      "id": "4c34118b-...",
      "created_at": "2025-11-02T04:30:00+00:00",
      "updated_at": "2026-08-01T09:15:00+00:00",
      "name": "Shree Balaji Auto Components",
      "category": "Automotive Fasteners",
      "gstin": "27AABCS1429B1ZP",
      "udyam_number": "UDYAM-MH-26-0012345",
      "phone": "+91-98230-11223",
      "languages": ["hi", "mr", "en"],
      "city": "Pune",
      "state": "Maharashtra",
      "lat": 18.5204,
      "lng": 73.8567,
      "reliability_score_0_100": 82,
      "on_time_rate": 0.91,
      "orders_completed": 214,
      "disputes": 3,
      "dues_paise": 184500000,
      "dues_display": "₹18,45,000"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/vendors/{id}`

Same shape as one item above. 404 if not found.

### `GET /api/v1/vendors/dues`

Aggregated dues across all vendors with `dues_paise > 0`.

```json
{
  "items": [
    {
      "vendor": { "id": "4c34118b-...", "name": "Shree Balaji Auto Components", "gstin": "27AABCS1429B1ZP" },
      "total_due_paise": 184500000,
      "total_due_display": "₹18,45,000",
      "oldest_invoice_age_days": 30,
      "invoice_count": 1
    }
  ],
  "total_due_paise": 965500000,
  "total_due_display": "₹96,55,000"
}
```

---

### `GET /api/v1/dashboard/summary`

```json
{
  "active_disruptions": 3,
  "exposure_at_risk_paise": 3030000000,
  "exposure_at_risk_display": "₹3,03,00,000",
  "exposure_mitigated_paise": 0,
  "exposure_mitigated_display": "₹0",
  "disruptions_closed_today": 0,
  "stage_counts": [{ "stage": "SETTLEMENT_PENDING", "count": 1 }],
  "vendors_dues_total_paise": 965500000,
  "vendors_dues_total_display": "₹96,55,000",
  "updated_at": "2026-08-09T06:00:00+00:00"
}
```

---

### `POST /api/v1/approvals/{approval_id}/decision`

**Request:**
```json
{
  "decision": "APPROVE",
  "channel": "WEB",
  "decided_by": "priya.sharma@mahe-industries.in",
  "note": "optional free text",
  "idempotency_key": "a client-generated UUID or unique string"
}
```
`decision` ∈ `APPROVE | REJECT | REQUEST_OPTIONS`. `channel` ∈ `WEB | WHATSAPP | VOICE | SYSTEM`.

**Response:**
```json
{
  "approval": {
    "id": "a52a6e18-...",
    "status": "APPROVED",
    "requested_at": "2026-08-07T04:00:00+00:00",
    "decided_at": "2026-08-07T04:22:00+00:00",
    "decided_by": "priya.sharma@mahe-industries.in",
    "channel": "WEB"
  },
  "disruption_id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "new_stage": "APPROVED"
}
```

**Idempotency**: replaying the same `idempotency_key` returns the identical
cached response — it does not error and does not re-apply the decision. 404 if
`approval_id` doesn't match any disruption's approval.

---

### `POST /api/v1/settlements/{batch_id}/execute`

**Request:** `{ "idempotency_key": "...", "executed_by": "finance.ops@mahe-industries.in" }`

**Response:**
```json
{
  "batch": { "...SettlementBatch": "...", "status": "EXECUTING" },
  "transaction_agent": {
    "thread_id": "b3f1...-uuid",
    "status": "pending_approval",
    "review_text": "1. ₹18,45,000 to Shree Balaji Auto Components\n2. ..."
  }
}
```

Idempotent on `idempotency_key`, same pattern as approvals.

`transaction_agent` is the result of handing this batch off to the
transaction-agent service (`../transaction-agent`) as a `POST /requests`
natural-language payment request — see
`app/transaction_agent_client.py`. **Best-effort, not authoritative**:
`null` if transaction-agent is unreachable or not running; Sanjeevani's own
settlement state (`batch.status`) still transitions to `EXECUTING`
regardless. When present, `status` is transaction-agent's own thread
status (`pending_approval` | `pending_recipient_disambiguation`) — a human
still has to approve the thread on transaction-agent's side (CLI, its own
API, or the voice channel) before anything actually executes there; this
call only stages it.

---

### `GET /api/v1/audit/{disruption_id}`

Full agent-action audit trail for a disruption. 404 if the disruption doesn't exist.

```json
{
  "disruption_id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "entries": [
    {
      "id": "c6d35d39-...",
      "at": "2026-08-07T03:12:00+00:00",
      "agent": "SENTINEL",
      "action": "SIGNAL_RAISED",
      "detail": "Carrier tracking gap exceeded 12h threshold",
      "input_summary": "GPS ping stream for shipment SHP-88213",
      "output_summary": "DELIVERY_DELAY disruption opened"
    }
  ]
}
```

---

### `GET /api/v1/metrics/demo`

```json
{
  "latency": {
    "detection_to_alert_seconds": { "p50": 4.2, "p95": 9.8, "last": 5.1 },
    "alert_to_decision_seconds": { "p50": 620.0, "p95": 1840.0, "last": 1320.0 },
    "decision_to_negotiated_seconds": { "p50": 940.0, "p95": 2100.0, "last": 960.0 },
    "end_to_end_seconds": { "p50": 1980.0, "p95": 4600.0, "last": 2340.0 }
  },
  "totals": {
    "exposure_identified_paise": 30300000000,
    "exposure_identified_display": "₹30.3Cr",
    "exposure_mitigated_paise": 18900000000,
    "exposure_mitigated_display": "₹18.9Cr",
    "disruptions_closed": 27
  },
  "integrations": {
    "watsonx": "STUB", "guardian": "STUB", "supermemory": "STUB",
    "verification": "STUB", "ttm": "STUB",
    "orchestrate": "NOT_CONFIGURED", "neon": "NOT_CONFIGURED"
  }
}
```

Each integration value ∈ `LIVE | STUB | UNAVAILABLE | NOT_CONFIGURED`.

---

### `GET /api/v1/forecast/{sku}`

404 if no forecast exists for the SKU. Known mock SKUs: `CRS-2MM`, `M8-HEX-BOLT`.

```json
{
  "sku": "CRS-2MM",
  "history": [{ "at": "2026-07-01T00:00:00+00:00", "value": 58.2 }],
  "forecast": [{ "at": "2026-08-12T00:00:00+00:00", "value": 67.5 }],
  "reorder_point": 65.0,
  "projected_breach_at": "2026-08-14T00:00:00+00:00",
  "model": "granite-timeseries-ttm-r2"
}
```

`model` ∈ `granite-timeseries-ttm-r2 | RULE_BASED`.

---

### `WS /api/v1/live`

See the [WebSocket event catalogue](#websocket-event-catalogue) below.

---

### `POST /api/v1/disruptions/simulate` (dev-only, Phase 4a/4b, extended Demo D0)

Not part of the stable contract — a demo/dev trigger, gated on `DEMO_MODE`
(default on; 404s when off in a real deployment). Either path runs the
Diagnosis and Sourcing agents and stops at `AWAITING_APPROVAL` (the human
gate — see `CLAUDE.md`'s orchestrator section).

**Request body — two mutually exclusive shapes:**

1. **Named golden-path scenario** (unchanged since Phase 4a — the frontend
   and this README both depend on these two names still working exactly as
   before):
   ```json
   { "scenario": "delivery_delay_castings" }
   ```
   Supported `scenario` values:
   - `"delivery_delay_castings"` — rule-based `overdue_delivery` detector;
     resulting disruption's `detector_source` is `RULE_BASED`.
   - `"stockout_risk"` — Phase 4b's TTM detector; resulting disruption's
     `detector_source` is `TTM_FORECAST` — this is the one to point at when
     the pitch needs "this alert came from IBM's time-series model, not a
     rule."

2. **Free-form vendor + kind** (Demo phase D0 — any seeded vendor, not just
   the two golden-path ones; see `GET /api/v1/simulate/targets` below for
   candidates):
   ```json
   { "vendor_id": "1f085369-1380-4c55-9cbc-f447ccd95df9", "kind": "DELAYED", "effective_date": "2026-08-14" }
   ```
   `vendor_id` and `kind` must be supplied together. `effective_date` is
   optional free-form context stored on the signal, not validated against
   any schedule. `kind` maps to `DisruptionType` as follows:

   | `kind` (`ScenarioKind`) | `DisruptionType` |
   |---|---|
   | `BACKED_OUT` | `VENDOR_UNRESPONSIVE` |
   | `PRICE_HIKE` | `PRICE_SHOCK` |
   | `DELAYED` | `DELIVERY_DELAY` |
   | `SHUT_DOWN` | `VENDOR_UNRESPONSIVE` |

   The resulting disruption's `detector_source` is `RULE_BASED` and
   `detector_name` is `demo_manual_trigger` — distinct from every real
   Sentinel detector name so it can never collide with an actual signal for
   the same vendor. 404 if `vendor_id` doesn't match a seeded vendor.

Neither shape re-runs the pipeline on a disruption that's already progressed
past `DETECTED` — the endpoint just reports its current stage
(`newly_triggered: false`).

**Response (same shape for both request forms):**
```json
{
  "disruption_id": "3b0b46e1-...",
  "scenario": "delivery_delay_castings",
  "stage": "AWAITING_APPROVAL",
  "newly_triggered": true
}
```
For the free-form path, `scenario` in the response echoes back as
`"custom:<kind>"` (e.g. `"custom:DELAYED"`) since there's no named scenario.

422 if the request has neither a `scenario` nor a `vendor_id`+`kind` pair.
400 for an unknown scenario name (named-scenario path only); 404 if the seed
vendor is missing (reseed with `python -m app.seed --reset`, or for the
free-form path, if `vendor_id` doesn't exist); 422 (named-scenario path only)
if Sentinel didn't detect the expected signal (the golden-path seed data may
already be consumed by a prior run).

Follow up with `GET /api/v1/disruptions/{disruption_id}` to see the full
result — real exposure breakdown, diagnosis, ranked+verified candidates, and
timeline, all produced by the agents in `app/agents/`.

---

### `GET /api/v1/simulate/targets` (dev-only, Demo D0)

Lists seeded vendors that make good demo targets, so the frontend's trigger
modal can populate a dropdown instead of anyone pasting a UUID on stage.
Gated on `DEMO_MODE` like `/disruptions/simulate`. Only vendors with at least
one open (undelivered) purchase order are included, sorted by
`est_exposure_paise` descending, capped at 10.

```json
{
  "items": [
    {
      "vendor_id": "1f085369-1380-4c55-9cbc-f447ccd95df9",
      "name": "Marudhar Steel Traders",
      "category": "Castings",
      "open_po_count": 4,
      "downstream_line_count": 1,
      "est_exposure_paise": 92000000,
      "recommended_kinds": ["BACKED_OUT", "PRICE_HIKE", "DELAYED", "SHUT_DOWN"]
    }
  ]
}
```

`est_exposure_paise` is computed the same way `app/services/exposure.py`
computes a real disruption's exposure (blocked inventory value + any
contractual delay penalties on POs with a downstream order), just run
ahead of time against the vendor's currently-open POs with no idle-line
cost and no backup quote yet — it's a rough pre-trigger estimate, not the
number a triggered disruption will actually settle on. `recommended_kinds`
is currently every `ScenarioKind` value for every listed vendor (any seeded
vendor can plausibly experience any disruption kind); this may narrow to
per-vendor recommendations post-D0.

---

## Demo control plane (dev-only, Demo D0)

### `POST /api/v1/demo/reset`

Gated on `DEMO_MODE`. Clears `disruption_events`, `exposure_calcs`,
`vendor_candidates`, `approvals`, `negotiations`, `audit_log`, `agent_runs`,
`verifications` (FK-required — see `CLAUDE.md`), and the WS ring buffer, then
re-seeds the three legacy golden-path disruptions (same shape
`python -m app.seed --reset` produces for them). Vendors, purchase orders,
inventory snapshots, comm events, and settlement batches are **not** touched
— this is a targeted disruption-lifecycle reset, not a schema rebuild (no
`drop_all`/`create_all` — that path deadlocks against a running server, see
`CLAUDE.md`). Runs in well under 5 seconds with the server up.

**Response:**
```json
{
  "cleared": {
    "agent_runs": 12,
    "audit_log": 9,
    "vendor_candidates": 1,
    "verifications": 1,
    "negotiations": 1,
    "approvals": 2,
    "exposure_calcs": 3,
    "disruption_events": 3,
    "ws_ring_buffer": 4
  },
  "reseeded_disruptions": 3,
  "elapsed_ms": 340.2
}
```

### `GET /api/v1/demo/state`

Gated on `DEMO_MODE`. A single status object for a demo-status screen or a
poll loop — cheaper than assembling the same picture from several other
endpoints.

```json
{
  "disruption_count_by_stage": [
    { "stage": "DETECTED", "count": 1 },
    { "stage": "AWAITING_APPROVAL", "count": 1 },
    { "stage": "SETTLEMENT_PENDING", "count": 1 }
  ],
  "integrations": {
    "watsonx": "STUB", "guardian": "STUB", "supermemory": "STUB",
    "verification": "STUB", "ttm": "LIVE",
    "orchestrate": "NOT_CONFIGURED", "neon": "NOT_CONFIGURED"
  },
  "ttm_loaded": true,
  "ws_client_count": 2,
  "db_roundtrip_ms": 41.3,
  "updated_at": "2026-08-09T06:00:00+00:00"
}
```

`integrations` reuses the same fixture-backed values `GET /metrics/demo`
returns (see `CLAUDE.md` — that endpoint remains fixture-backed even with
`USE_MOCKS=false`). `ttm_loaded` is `app.agents.detectors.ttm_forecast.is_available()`
directly, not the `integrations.ttm` string, so it's true/false the instant
the background model load finishes rather than waiting on the fixture value.
`db_roundtrip_ms` is a fresh blocking `SELECT 1`, same mechanism as the
startup connectivity check — `-1` if the query itself failed.

---

## Voice/settlement-agent-facing endpoints (Person 3)

### `GET /api/v1/vendors/{vendor_id}/context`

**Called mid-phone-call — kept small and fast.** 404 if vendor or context is
unavailable.

```json
{
  "vendor": {
    "id": "4c34118b-...", "name": "Shree Balaji Auto Components",
    "category": "Automotive Fasteners", "gstin": "27AABCS1429B1ZP",
    "phone": "+91-98230-11223", "languages": ["hi", "mr", "en"]
  },
  "reliability": { "score_0_100": 82, "on_time_rate": 0.91, "orders_completed": 214, "disputes": 3 },
  "last_terms": { "unit_price_paise": 1450, "lead_time_days": 2, "payment_terms_days": 30, "agreed_at": "2026-08-07T04:41:00+00:00" },
  "history_summary": "Long-standing fastener supplier for Chakan plant, 214 orders completed at a 91% on-time rate...",
  "briefing": "Shree Balaji is a reliable fastener vendor who just agreed to expedite your last order — greet them warmly and reference the recent 2-day turnaround.",
  "guardrails": { "max_unit_price_paise": 1600, "max_lead_time_days": 4, "requires_human_above_paise": 500000000 },
  "memory_source": "SUPERMEMORY"
}
```

Constraints the voice agent can rely on: `history_summary` ≤ 400 chars, plain
prose, no markdown. `briefing` ≤ 300 chars, one sentence, speakable as-is.
`memory_source` ∈ `SUPERMEMORY | DB_ONLY | UNAVAILABLE`.

---

### `POST /api/v1/negotiations/{negotiation_id}/outcome`

**Request:**
```json
{
  "outcome": "AGREED",
  "final_unit_price_paise": 1400,
  "final_lead_time_days": 2,
  "final_payment_terms_days": 30,
  "transcript_summary": "Vendor agreed to revised pricing after volume commitment.",
  "idempotency_key": "..."
}
```

**Response:**
```json
{
  "negotiation_id": "192864e3-...",
  "status": "AGREED",
  "disruption_id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "new_stage": "NEGOTIATED"
}
```

404 if `negotiation_id` doesn't match any disruption's negotiation. Idempotent
on `idempotency_key`.

---

### `GET /api/v1/settlement/batch?month=`

`month` optional, format `YYYY-MM`.

```json
{
  "items": [
    {
      "id": "a7a105e1-...",
      "created_at": "2026-08-01T00:00:00+00:00",
      "updated_at": "2026-08-07T04:45:00+00:00",
      "month": "2026-08",
      "status": "PENDING",
      "total_paise": 212500000,
      "total_display": "₹21,25,000",
      "lines": [
        {
          "vendor": { "id": "4c34118b-...", "name": "Shree Balaji Auto Components", "gstin": "27AABCS1429B1ZP" },
          "invoice_id": "INV-SB-20260731-04",
          "amount_paise": 184500000,
          "amount_display": "₹18,45,000",
          "due_date": "2026-08-15"
        }
      ],
      "confirmed_at": null,
      "confirmed_by": null
    }
  ],
  "total": 1
}
```

### `POST /api/v1/settlement/{batch_id}/confirm`

**Request:** `{ "idempotency_key": "...", "confirmed_by": "finance.ops@mahe-industries.in" }`

**Response:** `{ "batch": { ...SettlementBatch, "status": "CONFIRMED", "confirmed_at": "...", "confirmed_by": "..." } }`

Idempotent on `idempotency_key`. Note this path is singular (`/settlement/`)
while the execute endpoint above is plural (`/settlements/`) — that's the
locked contract, not a typo; see `CLAUDE.md`.

## Demo mock UI (D4)

### `GET /api/v1/phone/messages?disruption_id=`

**WhatsApp Business API integration: NOT implemented.** This endpoint and the
frontend's phone UI are the honest deliverable — message thread derived from
existing database state (disruption alerts, approval cards, negotiation
outcomes, settlement updates), deterministically sorted oldest first.

**Response:** `{ "messages": [ { "id", "at", "direction": "IN"|"OUT", "kind":
"TEXT"|"ALERT"|"APPROVAL_CARD"|"RESULT", "text", "card"?: { "disruption_id",
"approval_id", "headline", "exposure_display", "plan_summary": ["action1",
"action2"], "actions": ["APPROVE","MODIFY"] } } ] }`

The `card` field is only present for `kind: "APPROVAL_CARD"` messages. The
thread is deterministic — the same DB state always produces the same sequence.
This is the communication layer as far as the demo goes: outbound messages are
DB state queries, not Twilio/WhatsApp-Business-API calls.

---

## WebSocket event catalogue

Connect to `ws://localhost:8000/api/v1/live`. On connect, the last 50 buffered
events are replayed immediately, then the connection streams live events. A
`HEARTBEAT` event fires every 20 seconds. In mock mode
(`MOCK_LIVE_REPLAY=true`), a scripted disruption story is broadcast every 45
seconds so there's always something to build against.

**Every message has this envelope:**

```json
{
  "event_id": "uuid4",
  "type": "STAGE_CHANGED",
  "at": "2026-08-09T06:00:00+00:00",
  "disruption_id": "981f074f-9332-4b66-a24d-ffcaff0144cf",
  "payload": { "...": "type-specific fields, see below" }
}
```

`disruption_id` is `null` for events not tied to a specific disruption (e.g. some
`AGENT_STATUS_CHANGED` events, `HEARTBEAT`).

| `type` | When it fires | Example `payload` |
|---|---|---|
| `AGENT_STATUS_CHANGED` | An agent's status changes | `{ "agent": "DIAGNOSIS", "status": "RUNNING" }` |
| `DISRUPTION_CREATED` | A new disruption is detected | `{ "headline": "..." }` |
| `STAGE_CHANGED` | A disruption moves to a new stage | `{ "stage": "APPROVED" }` |
| `EXPOSURE_COMPUTED` | Exposure estimate is (re)computed | `{ "total_paise": 260000000, "total_display": "₹26,00,000" }` |
| `CANDIDATES_FOUND` | Sourcing candidates are matched | `{ "count": 2 }` |
| `APPROVAL_REQUESTED` | A disruption needs a human decision | `{ "channel": "WEB" }` |
| `APPROVAL_DECIDED` | A decision was made via `POST /approvals/{id}/decision` | `{ "approval_id": "...", "decision": "APPROVE", "new_stage": "APPROVED" }` |
| `NEGOTIATION_UPDATE` | Negotiation status changes, incl. via `POST /negotiations/{id}/outcome` | `{ "negotiation_id": "...", "status": "AGREED" }` |
| `SETTLEMENT_STAGED` | A settlement batch is executed/confirmed | `{ "batch_id": "...", "status": "CONFIRMED" }` |
| `FORECAST_ALERT` | A TTM forecast crosses a breach threshold | `{ "sku": "CRS-2MM", "projected_breach_at": "..." }` |
| `HEARTBEAT` | Every 20s, keep-alive | `{}` |
| `IMPACT_COMPUTED` | The disruption's downstream impact graph is (re)computed — **live since Demo D1**, fires during `POST /disruptions/simulate`'s pipeline run, between the DIAGNOSED and SOURCING transitions | see below |
| `PLAN_PROPOSED` | A mitigation plan (candidate changes) is proposed for a disruption | see below |
| `CALL_STARTED` | A voice negotiation call begins | see below |
| `CALL_TRANSCRIPT` | A transcript chunk streams in from an active call | see below |
| `CALL_FIELD_EXTRACTED` | A structured field is extracted mid-call | see below |
| `CALL_ENDED` | A voice negotiation call ends | see below |
| `INGEST_PROGRESS` | A document ingestion job's status changes | see below |
| `BRIEFING_READY` | A pre-call vendor briefing finishes generating | see below |

**Demo phase D0 note:** the 8 event types above were documented ahead of any
emitting code so the frontend could build against their shape in parallel.
**Update (D1): `IMPACT_COMPUTED` is now live** — its payload is the full
`ImpactGraph` object (same shape as `GET /disruptions/{id}/impact`'s
response), not the smaller placeholder shown in D0's original note. The
other 7 are still unemitted; see `CLAUDE.md`'s "Demo phases" section for
which phase owns which. Sample payloads:

```json
// IMPACT_COMPUTED — the full ImpactGraph, see GET /disruptions/{id}/impact above
{ "disruption_id": "...", "nodes": [ /* ... */ ], "edges": [ /* ... */ ], "summary": { /* ... */ }, "computed_at": "..." }

// PLAN_PROPOSED
{
  "plan_id": "b1e2...-uuid",
  "changes": [
    { "kind": "SWITCH_VENDOR", "description": "Move remaining M8 bolt volume to Kohinoor Precision" },
    { "kind": "EXPEDITE_FREIGHT", "description": "Air-freight the in-transit balance" }
  ]
}

// CALL_STARTED
{ "call_id": "c7a1...-uuid", "vendor_id": "4c34118b-...", "status": "DIALING" }

// CALL_TRANSCRIPT
{ "call_id": "c7a1...-uuid", "speaker": "AGENT", "text": "Hi, calling about PO-SB-004's delivery delay..." }

// CALL_FIELD_EXTRACTED
{ "call_id": "c7a1...-uuid", "field": "final_unit_price_paise", "value": 1450 }

// CALL_ENDED
{ "call_id": "c7a1...-uuid", "status": "CONFIRMED", "duration_seconds": 184 }

// INGEST_PROGRESS
{ "ingest_id": "d92f...-uuid", "status": "PARSING", "progress_pct": 40 }

// BRIEFING_READY
{ "vendor_id": "4c34118b-...", "briefing": "Shree Balaji is a reliable fastener vendor..." }
```

`GraphNodeKind` (`VENDOR | ITEM | LINE | ORDER | PLANT`) and `GraphNodeState`
(`HEALTHY | AT_RISK | IMPACTED | SUBSTITUTED`) are the enums the impact graph
behind `IMPACT_COMPUTED` is built from — not yet exposed on a REST endpoint
as of D0. `CallStatus` (`DIALING | CONNECTED | NEGOTIATING | CONFIRMED |
FAILED | ENDED`) is the enum backing the `CALL_*` events' `status` field.
`PlanChangeKind` (`SPLIT_ORDER | SWITCH_VENDOR | PULL_FORWARD_STOCK |
REDUCE_QUANTITY | EXPEDITE_FREIGHT`) backs `PLAN_PROPOSED`'s `changes[].kind`.
`IngestStatus` (`QUEUED | PARSING | RESOLVED | FAILED`) backs
`INGEST_PROGRESS`'s `status` field.

---

## Error shape

All errors are standard FastAPI/Starlette JSON: `{ "detail": "..." }` with the
appropriate HTTP status code (404 for not-found, 401 for missing/invalid
`X-API-Key` when `REQUIRE_API_KEY=true`, 422 for request validation failures).
