"use client";

import clsx from "clsx";
import type { AgentName, AgentState, AgentStatusValue } from "@/lib/types";
import TileGrid from "./ui/TileGrid";

// Container tint behind, matching solid ink on top — the shared chip pairing.
const STATUS_CHIP: Record<AgentStatusValue, string> = {
  IDLE: "bg-neutral-dim text-neutral",
  RUNNING: "bg-info-dim text-info",
  DONE: "bg-success-dim text-success",
  BLOCKED: "bg-critical-dim text-critical",
  ERROR: "bg-critical-dim text-critical",
};

const STATUS_DOT: Record<AgentStatusValue, string> = {
  IDLE: "bg-neutral",
  RUNNING: "bg-info",
  DONE: "bg-success",
  BLOCKED: "bg-critical animate-blink",
  ERROR: "bg-critical animate-blink",
};

const STATUS_LABEL: Record<AgentStatusValue, string> = {
  IDLE: "Idle",
  RUNNING: "Running",
  DONE: "Done",
  BLOCKED: "Blocked",
  ERROR: "Error",
};

const AGENT_LABEL: Record<AgentName, string> = {
  SENTINEL: "Sentinel",
  DIAGNOSIS: "Diagnosis",
  SOURCING: "Sourcing",
  NEGOTIATION: "Negotiation (Bolna)",
  SETTLEMENT: "Settlement",
  GOVERNANCE: "Governance",
};

export default function AgentStatusStrip({ agents }: { agents: AgentState[] }) {
  return (
    <TileGrid minWidth={200}>
      {agents.map((agent) => (
        <div key={agent.name} className="shadow-panel flex flex-col gap-2 rounded-lg bg-surface p-4">
          <div className="flex items-start justify-between gap-2">
            <span className="eyebrow truncate">{AGENT_LABEL[agent.name]}</span>
            <span
              className={clsx(
                "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wider uppercase",
                STATUS_CHIP[agent.status]
              )}
            >
              <span className={clsx("size-1.5 shrink-0 rounded-full", STATUS_DOT[agent.status])} />
              {STATUS_LABEL[agent.status]}
            </span>
          </div>
          <span className="truncate text-xs text-ink-muted">{agent.current_task ?? "—"}</span>
        </div>
      ))}
    </TileGrid>
  );
}
