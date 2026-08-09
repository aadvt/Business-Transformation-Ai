"use client";

import { Clock, IndianRupee } from "lucide-react";
import clsx from "clsx";
import type { DisruptionStage, DisruptionSummary } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

const STAGE_BORDER: Partial<Record<DisruptionStage, string>> = {
  AWAITING_APPROVAL: "border-l-critical",
  NEGOTIATING: "border-l-accent",
  NEGOTIATED: "border-l-accent",
  SETTLED: "border-l-success",
  CLOSED: "border-l-success",
  REJECTED: "border-l-neutral",
  FAILED: "border-l-critical",
};

const DIMMED_STAGES: DisruptionStage[] = ["REJECTED", "CLOSED", "FAILED"];

export default function DisruptionRow({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <div
      className={clsx(
        "panel border-l-2 px-3 py-2.5 mb-1.5 flex flex-wrap items-center justify-between gap-4 row-hover",
        STAGE_BORDER[disruption.stage] ?? "border-l-info",
        DIMMED_STAGES.includes(disruption.stage) && "opacity-60"
      )}
    >
      <div className="flex min-w-[12rem] flex-col gap-0.5">
        <span className="text-[13px] font-medium text-ink">{disruption.vendor.name}</span>
        <span className="text-xs text-ink-muted">{disruption.headline}</span>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-muted">
          <Clock size={14} /> {formatTimeAgo(disruption.detected_at)}
        </span>
        <span className="numeric inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-muted">
          <IndianRupee size={14} /> {disruption.exposure_total_display}
        </span>
        <StatusTag stage={disruption.stage} />
      </div>
    </div>
  );
}
