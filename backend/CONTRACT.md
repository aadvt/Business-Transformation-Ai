# Sanjeevani Backend — API Contract

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

---

## Error shape

All errors are standard FastAPI/Starlette JSON: `{ "detail": "..." }` with the
appropriate HTTP status code (404 for not-found, 401 for missing/invalid
`X-API-Key` when `REQUIRE_API_KEY=true`, 422 for request validation failures).
