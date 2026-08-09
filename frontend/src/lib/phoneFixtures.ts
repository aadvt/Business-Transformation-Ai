// Mock data for D4's /phone WhatsApp mock, used while
// GET /api/v1/phone/messages doesn't exist yet. Session-scoped, mutable —
// tapping Approve/Modify actually appends messages and resolves the card,
// same in-memory-registry pattern as directoryFixtures.ts's vendor
// registration. Publishes APPROVAL_DECIDED on fixtureBus so /command (a
// separate tab) reacts to it exactly like a real WS broadcast would.

import { publishFixtureEvent } from "./fixtureBus";
import { impactGraphFixture } from "./demoFixtures";
import type { ApprovalDecision, PhoneMessage } from "./types";

const DISRUPTION_ID = impactGraphFixture.disruption_id;
export const FIXTURE_APPROVAL_ID = "fixture-approval-1";

let messages: PhoneMessage[] = [
  {
    id: "m-system",
    kind: "SYSTEM",
    from: "AGENT",
    text: "Simulated interface — no real WhatsApp messages are sent.",
    at: "2026-08-09T05:58:00+00:00",
  },
  {
    id: "m1",
    kind: "TEXT",
    from: "AGENT",
    text: "Namaste! Flagging a delivery risk on the Chakan line — full details below.",
    at: "2026-08-09T05:59:10+00:00",
  },
  {
    id: "m2",
    kind: "APPROVAL_CARD",
    from: "AGENT",
    text: null,
    at: "2026-08-09T05:59:40+00:00",
    approval_id: FIXTURE_APPROVAL_ID,
    disruption_id: DISRUPTION_ID,
    headline: "M8 hex bolt shipment 6 days behind schedule, line stoppage risk at Chakan plant",
    exposure_display: "₹1,84,50,000",
    plan_summary: [
      "Split PO-88213 across Shree Balaji + Kohinoor Precision",
      "Pull forward 8,000 units from Chakan buffer stock",
      "Air-freight the split-order leg — 3 days faster",
    ],
    status: "PENDING",
  },
];

export function getPhoneMessagesFixture(): PhoneMessage[] {
  return messages;
}

export function decideFixtureApproval(approvalId: string, decision: ApprovalDecision): PhoneMessage {
  const newStatus = decision === "APPROVE" ? "APPROVED" : decision === "REJECT" ? "REJECTED" : "OPTIONS_REQUESTED";

  messages = messages.map((m) => (m.kind === "APPROVAL_CARD" && m.approval_id === approvalId ? { ...m, status: newStatus } : m));

  const confirmation: PhoneMessage = {
    id: `confirm-${Date.now()}`,
    kind: "TEXT",
    from: "OWNER",
    text: decision === "APPROVE" ? "Approved. Go ahead." : "Show me other options first.",
    at: new Date().toISOString(),
  };
  messages = [...messages, confirmation];

  publishFixtureEvent(
    "APPROVAL_DECIDED",
    { approval_id: approvalId, decision, new_stage: decision === "APPROVE" ? "APPROVED" : "AWAITING_APPROVAL" },
    DISRUPTION_ID
  );

  return confirmation;
}
