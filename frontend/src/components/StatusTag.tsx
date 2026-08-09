import Badge from "./ui/badge";
import type { DisruptionStage } from "@/lib/types";

const STAGE_CONFIG: Record<DisruptionStage, { tone: "accent" | "alert" | "positive" | "progress" | "idle" | "neutral"; label: string }> = {
  DETECTED: { tone: "progress", label: "Sensing" },
  DIAGNOSED: { tone: "progress", label: "Diagnosis" },
  SOURCING: { tone: "progress", label: "Sourcing" },
  AWAITING_APPROVAL: { tone: "alert", label: "Awaiting approval" },
  APPROVED: { tone: "accent", label: "Approved" },
  REJECTED: { tone: "idle", label: "Rejected" },
  NEGOTIATING: { tone: "accent", label: "Negotiating" },
  NEGOTIATED: { tone: "accent", label: "Negotiated" },
  SETTLEMENT_PENDING: { tone: "accent", label: "Settlement pending" },
  SETTLED: { tone: "positive", label: "Settled" },
  CLOSED: { tone: "positive", label: "Closed" },
  FAILED: { tone: "alert", label: "Failed" },
};

export default function StatusTag({ stage }: { stage: DisruptionStage }) {
  const config = STAGE_CONFIG[stage];
  return <Badge tone={config.tone}>{config.label}</Badge>;
}
