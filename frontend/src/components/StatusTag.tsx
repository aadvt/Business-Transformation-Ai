import { Tag } from "@carbon/react";
import { PIPELINE_STAGES } from "@/lib/types";
import type { Disruption } from "@/lib/types";

type TagColor =
  | "red"
  | "magenta"
  | "purple"
  | "blue"
  | "cyan"
  | "teal"
  | "green"
  | "gray"
  | "cool-gray"
  | "warm-gray"
  | "high-contrast"
  | "outline";

const STATUS_CONFIG: Record<Disruption["status"], { type: TagColor; label: (d: Disruption) => string }> = {
  active: { type: "blue", label: (d) => PIPELINE_STAGES[d.stageIndex].label },
  awaiting_approval: { type: "red", label: () => "Awaiting approval" },
  negotiating: { type: "purple", label: () => "Negotiating" },
  settled: { type: "green", label: () => "Settled" },
  rejected: { type: "gray", label: () => "Rejected" },
};

export default function StatusTag({ disruption }: { disruption: Disruption }) {
  const config = STATUS_CONFIG[disruption.status];
  return (
    <Tag type={config.type} size="sm">
      {config.label(disruption)}
    </Tag>
  );
}
