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
  complete: "bg-success border-success text-accent-ink",
  current: "bg-accent border-accent text-accent-ink animate-blink",
  pending: "bg-surface-2 border-line-strong text-ink-faint",
  invalid: "bg-critical border-critical text-accent-ink",
};

const CONNECTOR_CLASSES: Record<NodeState, string> = {
  complete: "bg-success",
  current: "bg-line-strong",
  pending: "bg-line-strong",
  invalid: "bg-line-strong",
};

export default function WaterfallPipeline({ disruption }: { disruption: DisruptionSummary }) {
  return (
    <div className="panel px-5 py-4">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h3 className="text-[15px] leading-tight font-semibold text-ink">{disruption.vendor.name}</h3>
          <p className="mt-1 text-[13px] text-ink-muted">{disruption.headline}</p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="numeric text-[15px] font-semibold text-accent" data-numeric>
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
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2",
                    DOT_CLASSES[state]
                  )}
                >
                  {state === "complete" && <Check size={14} />}
                  {state === "invalid" && <X size={14} />}
                  {(state === "current" || state === "pending") && <CircleDot size={11} />}
                </span>
                {i < PIPELINE_PHASES.length - 1 && (
                  <span className={clsx("mx-1.5 h-px flex-1", CONNECTOR_CLASSES[state])} />
                )}
              </div>
              <div className="mt-2 flex flex-col items-center gap-0.5 px-1 text-center">
                <span
                  className={clsx(
                    "text-[11px] font-semibold tracking-[0.04em] uppercase",
                    state === "pending" ? "text-ink-faint" : "text-ink"
                  )}
                >
                  {phase.label}
                </span>
                <span className="text-[11px] leading-snug text-ink-faint">{phase.description}</span>
              </div>
            </div>
          );
        })}
      </div>

      <p className="mt-4 border-t border-line pt-3 text-[11px] text-ink-faint">
        Detected {formatTimeAgo(disruption.detected_at)}
      </p>
    </div>
  );
}
