import clsx from "clsx";
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

// Chips carry the low-saturation container tint with the matching solid ink on
// top — the same pairing the token layer defines for every status colour, so a
// stage reads the same here as it does on a map node or an agent row.
const TONE_CLASS: Record<(typeof STAGE_CONFIG)[DisruptionStage]["tone"], string> = {
  accent: "bg-accent-dim text-accent before:bg-accent",
  alert: "bg-critical-dim text-critical before:bg-critical",
  positive: "bg-success-dim text-success before:bg-success",
  progress: "bg-info-dim text-info before:bg-info",
  idle: "bg-neutral-dim text-neutral before:bg-neutral",
  neutral: "bg-neutral-dim text-neutral before:bg-neutral",
};

export default function StatusTag({ stage }: { stage: DisruptionStage }) {
  const config = STAGE_CONFIG[stage];
  return (
    <span
      data-slot="badge"
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wider whitespace-nowrap uppercase before:size-1.5 before:shrink-0 before:rounded-full",
        TONE_CLASS[config.tone]
      )}
    >
      {config.label}
    </span>
  );
}
