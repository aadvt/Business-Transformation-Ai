// Mock data for D5b's call mode, used while POST /api/v1/calls/start,
// GET /api/v1/calls/{id}, and POST /api/v1/calls/{id}/replay don't exist yet.
// Same NEXT_PUBLIC_USE_FIXTURES gate as demoFixtures.ts (see api.ts) —
// without this, "Call vendor" and the DemoControlBar's mode-jump-to-"call"
// just error out in fixture/offline mode while everything else in D0-D4
// demos fine offline. Mirrors phoneFixtures.ts's pattern: a session-scoped
// mutable registry, driven forward on timers, publishing WS-shaped events on
// fixtureBus so CallView's useLiveEvents subscription reacts exactly like it
// would to a real webhook-driven reveal.
//
// The scripted call intentionally lands the agreed price *under* the max
// guardrail (₹16.20 vs a ₹16.50 ceiling) — a clean pass, not a breach. The
// guardrail-exceeded visual path (red badge, pulsing guardrail tile) is real
// code in CallView and exercises fine against a live backend payload that
// sets exceeds_guardrail: true; scripting a second breach fixture here would
// duplicate that path without adding coverage worth the complexity.

import { publishFixtureEvent } from "./fixtureBus";
import { impactGraphFixture } from "./demoFixtures";
import { candidatesFixture } from "./directoryFixtures";
import { formatPaiseFull } from "./format";
import type {
  CallBriefingSnapshot,
  CallFieldValidation,
  CallGuardianInfo,
  CallGuardrails,
  CallSession,
  CallStartRequest,
} from "./types";

const DISRUPTION_ID = impactGraphFixture.disruption_id;
export const FIXTURE_CALL_ID = "fixture-call-1";

const WINNER = candidatesFixture[0]; // Kohinoor Precision — same vendor the plan diff and candidate rail pick as the top match.

// ---- Timing (tune these during rehearsal) ----
// Real calls run ~90s live before the webhook lands; fixture mode compresses
// that so a rehearsal run doesn't sit idle for a minute and a half.
const CALL_CONNECT_DELAY_MS = 900;
const CALL_REVEAL_START_MS = 2200; // delay before the post-call reveal begins
const FIELD_REVEAL_LAG_MS = 1100; // how long after its triggering turn lands a field "extracts"
const CALL_END_BUFFER_MS = 2200; // delay after the last turn before CALL_ENDED fires

const MAX_UNIT_PRICE_PAISE = 1650;
const AGREED_UNIT_PRICE_PAISE = 1620;

const BRIEFING_SNAPSHOT: CallBriefingSnapshot = {
  vendor_id: WINNER.vendor_id,
  vendor_name: WINNER.name,
  phone: "+91 98•••••241",
  language: "Marathi",
  category: "CNC Machined Parts",
  item_name: "M8 Hex Bolt",
  required_qty: 30000,
  target_unit_price: formatPaiseFull(WINNER.quoted_unit_price_paise),
  max_unit_price: formatPaiseFull(MAX_UNIT_PRICE_PAISE),
  max_lead_time_days: 5,
  last_agreed_price: formatPaiseFull(1450),
  reliability: `${WINNER.reliability_score_0_100 ?? 91}/100`,
  briefing: `Namaste! We need 30,000 M8 hex bolts for our Chakan line. Target price is around ${formatPaiseFull(
    WINNER.quoted_unit_price_paise
  )} per unit, and we can go up to ${formatPaiseFull(MAX_UNIT_PRICE_PAISE)} if delivery is within 5 days. Please confirm availability, price, and delivery date.`,
  updated_at: new Date().toISOString(),
};

const GUARDRAILS: CallGuardrails = {
  max_unit_price_paise: MAX_UNIT_PRICE_PAISE,
  max_unit_price_display: formatPaiseFull(MAX_UNIT_PRICE_PAISE),
  max_lead_time_days: 5,
};

const TRANSCRIPT: { speaker: "AGENT" | "VENDOR"; text: string; at_offset_ms: number }[] = [
  {
    speaker: "AGENT",
    text: "Namaste! This is Sanjeevani calling on behalf of Mahe Industries — we have an urgent requirement for M8 hex bolts. Can you confirm availability?",
    at_offset_ms: 0,
  },
  { speaker: "VENDOR", text: "Yes, we have stock. How many units do you need?", at_offset_ms: 3400 },
  {
    speaker: "AGENT",
    text: "30,000 units, needed at our Chakan plant within 5 days. Our target price is around ₹14.90 per unit — can you work with that?",
    at_offset_ms: 7200,
  },
  { speaker: "VENDOR", text: "At that quantity, the best we can do is ₹16.20 per unit, delivered in 3 days.", at_offset_ms: 12400 },
  { speaker: "AGENT", text: "That works within our budget. Can you confirm the delivery date and payment terms?", at_offset_ms: 16600 },
  {
    speaker: "VENDOR",
    text: "Delivery by 12th August. Payment terms: 15 days from delivery, UPI to kohinoorprecision@upi.",
    at_offset_ms: 20800,
  },
];

const FIELD_EXTRACTIONS: { field: string; afterTurn: number; info: CallFieldValidation }[] = [
  { field: "availability_confirmed", afterTurn: 1, info: { value: true, valid: true } },
  { field: "quantity", afterTurn: 3, info: { value: 30000, valid: true } },
  {
    field: "unit_price",
    afterTurn: 3,
    info: { value: AGREED_UNIT_PRICE_PAISE, valid: true, exceeds_guardrail: AGREED_UNIT_PRICE_PAISE > MAX_UNIT_PRICE_PAISE },
  },
  { field: "delivery_date", afterTurn: 5, info: { value: "2026-08-12", valid: true } },
  { field: "payment_terms_days", afterTurn: 5, info: { value: 15, valid: true } },
  { field: "upi_id", afterTurn: 5, info: { value: "kohinoorprecision@upi", valid: true } },
];

interface FixtureCallRecord {
  session: CallSession;
  timers: ReturnType<typeof setTimeout>[];
}

const registry = new Map<string, FixtureCallRecord>();

function buildInitialSession(req: CallStartRequest): CallSession {
  return {
    id: FIXTURE_CALL_ID,
    disruption_id: req.disruption_id,
    vendor_id: req.vendor_id,
    status: "DIALING",
    source: req.mode === "REPLAY" ? "REPLAY" : "LIVE_BOLNA",
    started_at: new Date().toISOString(),
    ended_at: null,
    language: BRIEFING_SNAPSHOT.language,
    phone: BRIEFING_SNAPSHOT.phone,
    briefing_snapshot: BRIEFING_SNAPSHOT,
    guardrails: GUARDRAILS,
    transcript: [],
    extracted: {},
    validation: { fields: {} },
    correlation_method: null,
    outcome_status: null,
  };
}

function scheduleScript(callId: string) {
  const record = registry.get(callId);
  if (!record) return;
  for (const timer of record.timers) clearTimeout(timer);
  record.timers = [];

  const push = (fn: () => void, delay: number) => record.timers.push(setTimeout(fn, delay));

  push(() => {
    record.session = { ...record.session, status: "CONNECTED" };
  }, CALL_CONNECT_DELAY_MS);

  let seq = 0;
  for (const turn of TRANSCRIPT) {
    push(() => {
      seq += 1;
      const fullTurn = { seq, speaker: turn.speaker, text: turn.text, at_offset_ms: turn.at_offset_ms };
      record.session = { ...record.session, transcript: [...record.session.transcript, fullTurn] };
      publishFixtureEvent(
        "CALL_TRANSCRIPT",
        { call_id: callId, phase: "POST_CALL_REVEAL", ...fullTurn },
        record.session.disruption_id
      );
    }, CALL_REVEAL_START_MS + turn.at_offset_ms);
  }

  for (const extraction of FIELD_EXTRACTIONS) {
    const turn = TRANSCRIPT[extraction.afterTurn];
    push(() => {
      record.session = {
        ...record.session,
        validation: { fields: { ...(record.session.validation.fields ?? {}), [extraction.field]: extraction.info } },
      };
      publishFixtureEvent(
        "CALL_FIELD_EXTRACTED",
        { call_id: callId, field: extraction.field, ...extraction.info },
        record.session.disruption_id
      );
    }, CALL_REVEAL_START_MS + turn.at_offset_ms + FIELD_REVEAL_LAG_MS);
  }

  const lastTurn = TRANSCRIPT[TRANSCRIPT.length - 1];
  push(() => {
    const guardian: CallGuardianInfo = {
      status: "POLICY_CHECK_PASSED",
      passed: true,
      is_real_guardian: false,
      label: "Policy check passed",
    };
    record.session = { ...record.session, status: "CONFIRMED", ended_at: new Date().toISOString(), outcome_status: "CONFIRMED" };
    publishFixtureEvent(
      "CALL_ENDED",
      {
        call_id: callId,
        status: "CONFIRMED",
        outcome: "CONFIRMED",
        guardian,
        new_stage: "NEGOTIATED",
        exposure_after: { total_paise: 11000000, total_display: "₹1,10,000" },
        duration_seconds: Math.round((CALL_REVEAL_START_MS + lastTurn.at_offset_ms + CALL_END_BUFFER_MS) / 1000),
      },
      record.session.disruption_id
    );
  }, CALL_REVEAL_START_MS + lastTurn.at_offset_ms + CALL_END_BUFFER_MS);
}

export function startFixtureCall(req: CallStartRequest): CallSession {
  const session = buildInitialSession(req);
  registry.set(FIXTURE_CALL_ID, { session, timers: [] });
  scheduleScript(FIXTURE_CALL_ID);
  return session;
}

/** Refresh recovery: returns whatever the scripted call has produced so far,
 * synthesizing a fresh DIALING session if this id was never started in this
 * tab (e.g. a hard reload landed here before `startFixtureCall` ran). */
export function getFixtureCall(callId: string): CallSession {
  const record = registry.get(callId);
  if (record) return record.session;
  const session = buildInitialSession({ disruption_id: DISRUPTION_ID, vendor_id: WINNER.vendor_id, mode: "LIVE" });
  registry.set(callId, { session, timers: [] });
  return session;
}

export function replayFixtureCall(callId: string): CallSession {
  const prior = registry.get(callId)?.session;
  const session = buildInitialSession({
    disruption_id: prior?.disruption_id ?? DISRUPTION_ID,
    vendor_id: prior?.vendor_id ?? WINNER.vendor_id,
    mode: "REPLAY",
  });
  registry.set(callId, { session, timers: [] });
  scheduleScript(callId);
  return session;
}
