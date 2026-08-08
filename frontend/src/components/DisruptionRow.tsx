"use client";

import { Clock, IndianRupee } from "lucide-react";
import clsx from "clsx";
import { motion } from "framer-motion";
import type { DisruptionStage, DisruptionSummary } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

const STAGE_BORDER: Partial<Record<DisruptionStage, string>> = {
  AWAITING_APPROVAL: "border-l-alert",
  NEGOTIATING: "border-l-accent",
  NEGOTIATED: "border-l-accent",
  SETTLED: "border-l-positive",
  CLOSED: "border-l-positive",
  REJECTED: "border-l-idle",
  FAILED: "border-l-alert",
};

const DIMMED_STAGES: DisruptionStage[] = ["REJECTED", "CLOSED", "FAILED"];

export default function DisruptionRow({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <motion.div
      className={clsx(
        "glass rounded-2xl mb-2 flex flex-wrap items-center justify-between gap-4 border-l-[3px] px-4 py-3.5",
        STAGE_BORDER[disruption.stage] ?? "border-l-progress",
        DIMMED_STAGES.includes(disruption.stage) && "opacity-60"
      )}
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      whileHover={{ x: 4 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <div className="flex min-w-[12rem] flex-col gap-0.5">
        <span className="text-sm font-semibold text-ink">{disruption.vendor.name}</span>
        <span className="text-[0.8125rem] text-ink-muted">{disruption.headline}</span>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-muted">
          <Clock size={14} /> {formatTimeAgo(disruption.detected_at)}
        </span>
        <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-ink-muted">
          <IndianRupee size={14} /> {disruption.exposure_total_display}
        </span>
        <StatusTag stage={disruption.stage} />
      </div>
    </motion.div>
  );
}
