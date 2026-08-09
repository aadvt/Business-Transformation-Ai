// Mock data for the D0-D7 demo layer, used while the backend endpoints in
// CONTRACT.md are still being built. Every api.ts method that reads from
// here is gated on NEXT_PUBLIC_USE_FIXTURES=true — flip that env var to
// switch to the real backend, no code changes required.
//
// Ids/vendor names below are reused from backend/app/mocks/fixtures so the
// demo layer stays visually consistent with the four existing routes.

import { formatPaiseFull } from "./format";
import type { DemoState, GraphEdge, GraphNode, ImpactGraph, Plan, SimulateTarget } from "./types";

const SHREE_BALAJI_VENDOR_ID = "4c34118b-bbe1-4016-885d-e6bc7917b3b0";
const KOHINOOR_VENDOR_ID = "1799a38c-a9ed-4d03-b666-4784d6346a7b";

const IMPACT_GRAPH_NODES: GraphNode[] = [
  { id: "vendor-shree-balaji", kind: "VENDOR", label: "Shree Balaji Auto Components", state: "IMPACTED", layer: 0, badges: ["Primary"] },
  { id: "item-m8-hex-bolt", kind: "ITEM", label: "M8 Hex Bolt", state: "IMPACTED", layer: 1, badges: ["SKU-4821"] },
  { id: "line-chassis-weld", kind: "LINE", label: "Chassis Weld Line", state: "AT_RISK", layer: 2, badges: ["Chakan Plant"] },
  { id: "line-subframe-assy", kind: "LINE", label: "Subframe Assembly", state: "AT_RISK", layer: 2, badges: [] },
  { id: "order-po-88213", kind: "ORDER", label: "PO-88213", state: "AT_RISK", layer: 3, badges: ["₹18,45,000"] },
  { id: "order-po-88240", kind: "ORDER", label: "PO-88240", state: "HEALTHY", layer: 3, badges: [] },
  { id: "plant-chakan", kind: "PLANT", label: "Chakan Plant", state: "AT_RISK", layer: 4, badges: ["Maharashtra"] },
  { id: "vendor-kohinoor", kind: "VENDOR", label: "Kohinoor Precision Pvt Ltd", state: "SUBSTITUTED", layer: 0, badges: ["Backup"] },
];

const IMPACT_GRAPH_EDGES: GraphEdge[] = [
  { id: "e-vendor-item", source: "vendor-shree-balaji", target: "item-m8-hex-bolt", state: "IMPACTED", weight: 1 },
  { id: "e-item-weld", source: "item-m8-hex-bolt", target: "line-chassis-weld", state: "AT_RISK", weight: 0.8 },
  { id: "e-item-subframe", source: "item-m8-hex-bolt", target: "line-subframe-assy", state: "AT_RISK", weight: 0.6 },
  { id: "e-weld-po1", source: "line-chassis-weld", target: "order-po-88213", state: "AT_RISK", weight: 1 },
  { id: "e-subframe-po2", source: "line-subframe-assy", target: "order-po-88240", state: "HEALTHY", weight: 1 },
  { id: "e-weld-plant", source: "line-chassis-weld", target: "plant-chakan", state: "AT_RISK", weight: 1 },
  { id: "e-subframe-plant", source: "line-subframe-assy", target: "plant-chakan", state: "HEALTHY", weight: 1 },
  { id: "e-substitute", source: "vendor-kohinoor", target: "item-m8-hex-bolt", state: "SUBSTITUTED", weight: 0.5 },
];

export const impactGraphFixture: ImpactGraph = {
  disruption_id: "981f074f-9332-4b66-a24d-ffcaff0144cf",
  nodes: IMPACT_GRAPH_NODES,
  edges: IMPACT_GRAPH_EDGES,
  summary: {
    impacted_node_count: 4,
    at_risk_order_count: 1,
    exposure_paise: 1845000000,
    exposure_display: "₹1,84,50,000",
    tier: "HIGH",
  },
};

export const simulateTargetsFixture: SimulateTarget[] = [
  {
    vendor_id: SHREE_BALAJI_VENDOR_ID,
    name: "Shree Balaji Auto Components",
    category: "Automotive Fasteners",
    open_po_count: 3,
    downstream_line_count: 2,
    est_exposure_paise: 1845000000,
    recommended_kinds: ["DELAYED", "BACKED_OUT"],
  },
  {
    vendor_id: KOHINOOR_VENDOR_ID,
    name: "Kohinoor Precision Pvt Ltd",
    category: "CNC Machined Parts",
    open_po_count: 5,
    downstream_line_count: 3,
    est_exposure_paise: 942000000,
    recommended_kinds: ["PRICE_HIKE", "DELAYED"],
  },
  {
    vendor_id: "6e2d0a5b-6f0e-4c1a-9c34-6b1a2f0e9d21",
    name: "Marudhar Steel Traders",
    category: "Raw Steel Coil",
    open_po_count: 2,
    downstream_line_count: 4,
    est_exposure_paise: 3120000000,
    recommended_kinds: ["SHUT_DOWN", "PRICE_HIKE"],
  },
];

export const demoStateFixture: DemoState = {
  stage_counts: {
    DETECTED: 1,
    DIAGNOSED: 0,
    SOURCING: 0,
    AWAITING_APPROVAL: 2,
    NEGOTIATING: 1,
    SETTLEMENT_PENDING: 1,
    SETTLED: 3,
    CLOSED: 5,
  },
  integrations: {
    watsonx: "LIVE",
    guardian: "LIVE",
    supermemory: "STUB",
    verification: "LIVE",
    ttm: "LIVE",
    orchestrate: "STUB",
    neon: "LIVE",
  },
  ttm_loaded: true,
  ws_clients: 2,
  db_roundtrip_ms: 38,
};

function paise(rupees: number) {
  return { paise: rupees * 100, display: formatPaiseFull(rupees * 100) };
}

const eb = paise(640000);
const ea = paise(110000);
const cost = paise(84000);
const saving = paise(eb.paise / 100 - ea.paise / 100 - cost.paise / 100);

export const planFixture: Plan = {
  id: "plan-fixture-1",
  disruption_id: impactGraphFixture.disruption_id,
  exposure_before_paise: eb.paise,
  exposure_before_display: eb.display,
  exposure_after_paise: ea.paise,
  exposure_after_display: ea.display,
  cost_to_resolve_paise: cost.paise,
  cost_to_resolve_display: cost.display,
  net_saving_paise: saving.paise,
  net_saving_display: saving.display,
  requires_escalation: true,
  escalation_reason: "Cost to resolve exceeds ₹50,000 auto-approval threshold for this vendor category.",
  solver: "OR_TOOLS_CP_SAT",
  solve_ms: 340,
  changes: [
    {
      id: "change-split",
      kind: "SPLIT_ORDER",
      description: "Split PO-88213 across the incumbent and a verified backup",
      rationale:
        "Shree Balaji can still fulfil 40% of the order within the original window; the remaining 60% moves to Kohinoor Precision (91/100 reliability, 3-day lead) to protect the Chakan line's start date.",
      current: [
        {
          vendor_id: "4c34118b-bbe1-4016-885d-e6bc7917b3b0",
          vendor_name: "Shree Balaji Auto Components",
          item: "M8 Hex Bolt",
          qty: 50000,
          unit_price_paise: 1450,
          unit_price_display: formatPaiseFull(1450),
          lead_time_days: 6,
          eta: "2026-08-15",
        },
      ],
      proposed: [
        {
          vendor_id: "4c34118b-bbe1-4016-885d-e6bc7917b3b0",
          vendor_name: "Shree Balaji Auto Components",
          item: "M8 Hex Bolt",
          qty: 20000,
          unit_price_paise: 1450,
          unit_price_display: formatPaiseFull(1450),
          lead_time_days: 6,
          eta: "2026-08-15",
        },
        {
          vendor_id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
          vendor_name: "Kohinoor Precision Pvt Ltd",
          item: "M8 Hex Bolt",
          qty: 30000,
          unit_price_paise: 1490,
          unit_price_display: formatPaiseFull(1490),
          lead_time_days: 3,
          eta: "2026-08-12",
        },
      ],
    },
    {
      id: "change-switch",
      kind: "SWITCH_VENDOR",
      description: "Move the subframe bracket line to Kohinoor Precision",
      rationale: "Same spec, verified, and 3 days faster — the incumbent has no capacity left this cycle.",
      current: [
        {
          vendor_id: "4c34118b-bbe1-4016-885d-e6bc7917b3b0",
          vendor_name: "Shree Balaji Auto Components",
          item: "Subframe Bracket",
          qty: 10000,
          unit_price_paise: 2100,
          unit_price_display: formatPaiseFull(2100),
          lead_time_days: 8,
          eta: "2026-08-17",
        },
      ],
      proposed: [
        {
          vendor_id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
          vendor_name: "Kohinoor Precision Pvt Ltd",
          item: "Subframe Bracket",
          qty: 10000,
          unit_price_paise: 2180,
          unit_price_display: formatPaiseFull(2180),
          lead_time_days: 5,
          eta: "2026-08-14",
        },
      ],
    },
    {
      id: "change-pull-forward",
      kind: "PULL_FORWARD_STOCK",
      description: "Pull forward 8,000 units of M8 Hex Bolt from the Chakan buffer stock",
      rationale: "Internal buffer covers the gap for the first 2 days while the split order is in transit — no purchase, no vendor risk.",
      current: [],
      proposed: [
        {
          vendor_id: "internal-chakan-buffer",
          vendor_name: "Internal — Chakan Warehouse",
          item: "M8 Hex Bolt",
          qty: 8000,
          unit_price_paise: 0,
          unit_price_display: "₹0",
          lead_time_days: 0,
          eta: "2026-08-09",
        },
      ],
    },
    {
      id: "change-expedite",
      kind: "EXPEDITE_FREIGHT",
      description: "Air-freight Kohinoor's split-order leg",
      rationale: "Cuts 3 days off the standard road lead time at a modest premium — keeps the Chakan line's start date intact.",
      current: [
        {
          vendor_id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
          vendor_name: "Kohinoor Precision Pvt Ltd",
          item: "M8 Hex Bolt",
          qty: 30000,
          unit_price_paise: 1490,
          unit_price_display: formatPaiseFull(1490),
          lead_time_days: 6,
          eta: "2026-08-15",
        },
      ],
      proposed: [
        {
          vendor_id: "1799a38c-a9ed-4d03-b666-4784d6346a7b",
          vendor_name: "Kohinoor Precision Pvt Ltd",
          item: "M8 Hex Bolt",
          qty: 30000,
          unit_price_paise: 1620,
          unit_price_display: formatPaiseFull(1620),
          lead_time_days: 3,
          eta: "2026-08-12",
        },
      ],
    },
  ],
};
