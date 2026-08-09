"use client";

import { Check, CircleDot, X } from "lucide-react";
import clsx from "clsx";
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
  complete: "bg-success border-success text-white",
  current: "bg-accent border-accent text-[#1a1305] animate-blink",
  pending: "bg-surface-2 border-line-strong text-ink-faint",
  invalid: "bg-critical border-critical text-white",
};

const CONNECTOR_CLASSES: Record<NodeState, string> = {
  complete: "bg-success",
  current: "bg-line-strong",
  pending: "bg-line-strong",
  invalid: "bg-line-strong",
};

export default function WaterfallPipeline({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <div className="panel p-4 mb-5">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <span className="block text-base font-semibold text-ink">{disruption.vendor.name}</span>
          <span className="mt-0.5 block text-[0.8125rem] text-ink-muted">{disruption.headline}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="numeric text-[0.9375rem] font-semibold text-accent">
            {disruption.exposure_total_display}
          </span>
          <StatusTag stage={disruption.stage} />
        </div>
      </div>

      <div className="flex items-start overflow-x-auto pb-1">
        {PIPELINE_PHASES.map((phase, i) => {
          const state = getNodeState(disruption, i);
          return (
            <div key={phase.id} className="flex min-w-[6.5rem] flex-1 flex-col items-center">
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
            </div>
          );
        })}
      </div>

      <p className="mt-3 text-xs text-ink-muted">Detected {formatTimeAgo(disruption.detected_at)}</p>
    </div>
  );
}
