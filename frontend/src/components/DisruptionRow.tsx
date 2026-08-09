"use client";

import { Clock } from "lucide-react";
import clsx from "clsx";
import type { DisruptionStage, DisruptionSummary } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

/** A single status dot carries the stage colour — the row itself stays neutral
 *  so a long list reads as one surface rather than a stack of striped bars. */
const STAGE_DOT: Partial<Record<DisruptionStage, string>> = {
  AWAITING_APPROVAL: "bg-critical",
  NEGOTIATING: "bg-accent",
  NEGOTIATED: "bg-accent",
  SETTLED: "bg-success",
  CLOSED: "bg-success",
  REJECTED: "bg-neutral",
  FAILED: "bg-critical",
};

const DIMMED_STAGES: DisruptionStage[] = ["REJECTED", "CLOSED", "FAILED"];

export default function DisruptionRow({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <div
      className={clsx(
        "panel row-hover mb-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-3.5 py-3",
        DIMMED_STAGES.includes(disruption.stage) && "opacity-60"
      )}
    >
      <div className="flex min-w-[12rem] flex-1 items-start gap-2.5">
        <span
          className={clsx(
            "mt-1.5 h-2 w-2 shrink-0 rounded-full",
            STAGE_DOT[disruption.stage] ?? "bg-info"
          )}
        />
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="truncate text-[13px] font-medium text-ink">{disruption.vendor.name}</span>
          <span className="text-xs text-ink-muted">{disruption.headline}</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-faint">
          <Clock size={13} /> {formatTimeAgo(disruption.detected_at)}
        </span>
        <span className="numeric text-[13px] font-semibold whitespace-nowrap text-ink" data-numeric>
          {disruption.exposure_total_display}
        </span>
        <StatusTag stage={disruption.stage} />
      </div>
    </div>
  );
}
