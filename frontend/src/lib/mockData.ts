import type { AgentStatus, Disruption, SettlementDue, Vendor } from "./types";

export const VENDORS: Vendor[] = [
  { id: "v1", name: "Krishna Steel Traders", category: "Raw Material", city: "Ludhiana", reliabilityPct: 91 },
  { id: "v2", name: "Om Sai Packaging Co.", category: "Packaging", city: "Ahmedabad", reliabilityPct: 87 },
  { id: "v3", name: "Bharat Fasteners Pvt Ltd", category: "Components", city: "Pune", reliabilityPct: 95 },
  { id: "v4", name: "Ganesh Logistics", category: "Freight", city: "Nashik", reliabilityPct: 78 },
  { id: "v5", name: "Vishal Chemicals", category: "Raw Material", city: "Vapi", reliabilityPct: 83 },
  { id: "v6", name: "Shree Ram Electricals", category: "Components", city: "Coimbatore", reliabilityPct: 89 },
];

export const INITIAL_DISRUPTIONS: Disruption[] = [
  {
    id: "d1",
    vendorId: "v1",
    vendorName: "Krishna Steel Traders",
    category: "Raw Material",
    issue: "Delivery delayed 4 days — GST e-way bill not generated",
    detectedAt: new Date(Date.now() - 1000 * 60 * 26).toISOString(),
    exposureINR: 620000,
    stageIndex: 2,
    status: "awaiting_approval",
    backups: [
      { id: "b1", name: "Rohit Steel Suppliers", verified: true, etaDays: 2, priceDeltaPct: 4 },
      { id: "b2", name: "Anand Metal Works", verified: true, etaDays: 3, priceDeltaPct: 1 },
      { id: "b3", name: "Sunrise Steel Co.", verified: true, etaDays: 2, priceDeltaPct: 6 },
    ],
  },
  {
    id: "d2",
    vendorId: "v4",
    vendorName: "Ganesh Logistics",
    category: "Freight",
    issue: "Truck breakdown on NH48 — shipment stalled",
    detectedAt: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
    exposureINR: 214000,
    stageIndex: 3,
    status: "negotiating",
    backups: [
      { id: "b4", name: "Speedway Freight", verified: true, etaDays: 1, priceDeltaPct: 8 },
      { id: "b5", name: "Kaveri Transport", verified: true, etaDays: 1, priceDeltaPct: 3 },
    ],
  },
  {
    id: "d3",
    vendorId: "v2",
    vendorName: "Om Sai Packaging Co.",
    category: "Packaging",
    issue: "Raw material shortage at source",
    detectedAt: new Date(Date.now() - 1000 * 60 * 4).toISOString(),
    exposureINR: 96000,
    stageIndex: 1,
    status: "active",
    backups: [],
  },
  {
    id: "d4",
    vendorId: "v5",
    vendorName: "Vishal Chemicals",
    category: "Raw Material",
    issue: "Quality inspection flagged batch #A2291",
    detectedAt: new Date(Date.now() - 1000 * 60 * 55).toISOString(),
    exposureINR: 148000,
    stageIndex: 5,
    status: "settled",
    backups: [{ id: "b6", name: "Patel Chem Industries", verified: true, etaDays: 2, priceDeltaPct: 2 }],
    negotiatedTermsSummary: "Patel Chem Industries — 2 day delivery, +2% price, confirmed by voice agent",
  },
];

export const INITIAL_DUES: SettlementDue[] = [
  { id: "s1", vendorId: "v3", vendorName: "Bharat Fasteners Pvt Ltd", amountINR: 412000, dueDate: "2026-08-31", status: "pending" },
  { id: "s2", vendorId: "v6", vendorName: "Shree Ram Electricals", amountINR: 268500, dueDate: "2026-08-31", status: "pending" },
  { id: "s3", vendorId: "v2", vendorName: "Om Sai Packaging Co.", amountINR: 93200, dueDate: "2026-08-31", status: "pending" },
  { id: "s4", vendorId: "v5", vendorName: "Vishal Chemicals", amountINR: 148000, dueDate: "2026-08-31", status: "staged", sourceDisruptionId: "d4" },
  { id: "s5", vendorId: "v1", vendorName: "Krishna Steel Traders", amountINR: 620000, dueDate: "2026-08-31", status: "pending" },
];

export const INITIAL_AGENTS: AgentStatus[] = [
  { id: "sentinel", label: "Sentinel", state: "working", detail: "Watching 6 live signal feeds" },
  { id: "diagnosis", label: "Diagnosis", state: "working", detail: "Quantifying exposure for d3" },
  { id: "sourcing", label: "Sourcing", state: "idle", detail: "Idle — last match 6 min ago" },
  { id: "negotiation", label: "Negotiation (Bolna)", state: "working", detail: "On call with Speedway Freight" },
  { id: "governance", label: "Governance", state: "alert", detail: "1 approval pending" },
  { id: "settlement", label: "Settlement", state: "idle", detail: "Next batch in 4 days" },
];

const BACKUP_POOL: Record<string, Omit<import("./types").BackupVendor, "id">[]> = {
  "Raw Material": [
    { name: "Rohit Steel Suppliers", verified: true, etaDays: 2, priceDeltaPct: 4 },
    { name: "Anand Metal Works", verified: true, etaDays: 3, priceDeltaPct: 1 },
  ],
  Packaging: [
    { name: "Modern Packaging Solutions", verified: true, etaDays: 1, priceDeltaPct: 5 },
    { name: "Deccan Pack Co.", verified: true, etaDays: 2, priceDeltaPct: 2 },
  ],
  Components: [
    { name: "Precision Components Ltd", verified: true, etaDays: 2, priceDeltaPct: 3 },
    { name: "Nova Fasteners", verified: true, etaDays: 1, priceDeltaPct: 6 },
  ],
  Freight: [
    { name: "Speedway Freight", verified: true, etaDays: 1, priceDeltaPct: 8 },
    { name: "Kaveri Transport", verified: true, etaDays: 1, priceDeltaPct: 3 },
  ],
};

const ISSUE_POOL = [
  "Delivery delayed — customs clearance pending",
  "Partial shipment — inventory mismatch flagged",
  "Vendor unresponsive for 48 hours",
  "Quality inspection flagged incoming batch",
  "Route disruption due to local weather advisory",
];

let spawnCounter = 0;

export function generateBackups(category: string): import("./types").BackupVendor[] {
  spawnCounter += 1;
  return (BACKUP_POOL[category] ?? BACKUP_POOL["Raw Material"]).map((b, i) => ({
    ...b,
    id: `bk-${spawnCounter}-${i}`,
  }));
}

export function spawnRandomDisruption(): Disruption {
  spawnCounter += 1;
  const vendor = VENDORS[Math.floor(Math.random() * VENDORS.length)];
  const issue = ISSUE_POOL[Math.floor(Math.random() * ISSUE_POOL.length)];
  const backups = (BACKUP_POOL[vendor.category] ?? []).map((b, i) => ({
    ...b,
    id: `spawn-${spawnCounter}-${i}`,
  }));

  return {
    id: `spawn-${spawnCounter}`,
    vendorId: vendor.id,
    vendorName: vendor.name,
    category: vendor.category,
    issue,
    detectedAt: new Date().toISOString(),
    exposureINR: Math.round((60000 + Math.random() * 500000) / 1000) * 1000,
    stageIndex: 0,
    status: "active",
    backups,
  };
}
