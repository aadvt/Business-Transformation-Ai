"use client";

import clsx from "clsx";
import type { AgentName, AgentState, AgentStatusValue } from "@/lib/types";
import TileGrid from "./ui/TileGrid";

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
        <div key={agent.name} className="bg-surface p-3 flex items-start gap-2.5">
          <div
            className={clsx(
              "mt-1.5 shrink-0 w-1.5 h-1.5 rounded-full",
              STATUS_DOT[agent.status]
            )}
          />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="eyebrow">{AGENT_LABEL[agent.name]}</span>
            <span className="truncate text-xs text-ink-muted">
              {STATUS_LABEL[agent.status]} &middot; {agent.current_task ?? "—"}
            </span>
          </div>
        </div>
      ))}
    </TileGrid>
  );
}
