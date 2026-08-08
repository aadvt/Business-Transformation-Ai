"use client";

import { Check, CircleDot, X } from "lucide-react";
import clsx from "clsx";
import { motion } from "framer-motion";
import { PIPELINE_PHASES, phaseIndexForStage, isFailedStage, isTerminalStage } from "@/lib/types";
import type { DisruptionSummary } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

type NodeState = "complete" | "current" | "pending" | "invalid";

function getNodeState(disruption: DisruptionSummary, phaseIndex: number): NodeState {
  const currentPhase = phaseIndexForStage(disruption.stage);

  if (isFailedStage(disruption.stage)) {
    if (phaseIndex < currentPhase) return "complete";
    if (phaseIndex === currentPhase) return "invalid";
    return "pending";
  }
  if (isTerminalStage(disruption.stage)) return "complete";
  if (phaseIndex < currentPhase) return "complete";
  if (phaseIndex === currentPhase) return "current";
  return "pending";
}

const DOT_CLASSES: Record<NodeState, string> = {
  complete: "bg-positive border-positive text-[#04150c] shadow-[0_0_12px_currentColor]",
  current: "bg-accent border-accent text-[#1a1305] animate-pulse-glow shadow-[0_0_12px_currentColor]",
  pending: "bg-panel-raised border-border-strong text-ink-faint",
  invalid: "bg-alert border-alert text-white",
};

const CONNECTOR_CLASSES: Record<NodeState, string> = {
  complete: "bg-gradient-to-r from-positive to-positive/40",
  current: "bg-border-strong",
  pending: "bg-border-strong",
  invalid: "bg-border-strong",
};

export default function WaterfallPipeline({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <motion.div
      className="glass-panel rounded-2xl p-6 mb-5"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="block text-base font-semibold text-ink">{disruption.vendor.name}</span>
          <span className="mt-0.5 block text-[0.8125rem] text-ink-muted">{disruption.headline}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="tabular-money text-[0.9375rem] font-semibold text-accent-strong">
            {disruption.exposure_total_display}
          </span>
          <StatusTag stage={disruption.stage} />
        </div>
      </div>

      <div className="flex items-start overflow-x-auto pb-1">
        {PIPELINE_PHASES.map((phase, i) => {
          const state = getNodeState(disruption, i);
          return (
            <motion.div
              key={phase.id}
              className="flex min-w-[6.5rem] flex-1 flex-col items-center"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.06, type: "spring", stiffness: 300, damping: 30 }}
            >
              <div className="flex w-full items-center">
                <span
                  className={clsx(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2",
                    DOT_CLASSES[state]
                  )}
                >
                  {state === "complete" && <Check size={16} />}
                  {state === "invalid" && <X size={16} />}
                  {(state === "current" || state === "pending") && <CircleDot size={12} />}
                </span>
                {i < PIPELINE_PHASES.length - 1 && <span className={clsx("mx-1 h-0.5 flex-1", CONNECTOR_CLASSES[state])} />}
              </div>
              <div className="mt-2 flex flex-col items-center text-center">
                <span className={clsx("text-xs font-semibold", state === "pending" ? "text-ink-faint" : "text-ink")}>
                  {phase.label}
                </span>
                <span className="mt-0.5 text-[0.6875rem] text-ink-muted">{phase.description}</span>
              </div>
            </motion.div>
          );
        })}
      </div>

      <p className="mt-3 text-xs text-ink-muted">Detected {formatTimeAgo(disruption.detected_at)}</p>
    </motion.div>
  );
}
