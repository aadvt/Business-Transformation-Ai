"use client";

import { Circle } from "lucide-react";
import clsx from "clsx";
import { motion } from "framer-motion";
import type { AgentName, AgentState, AgentStatusValue } from "@/lib/types";
import TileGrid from "./ui/TileGrid";

const STATUS_DOT: Record<AgentStatusValue, string> = {
  IDLE: "fill-idle text-idle",
  RUNNING: "fill-progress text-progress",
  DONE: "fill-positive text-positive",
  BLOCKED: "fill-alert text-alert animate-pulse-glow",
  ERROR: "fill-alert text-alert animate-pulse-glow",
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
      {agents.map((agent, index) => (
        <motion.div
          key={agent.name}
          className="glass rounded-2xl p-4 flex items-start gap-2.5"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: index * 0.05, type: "spring", stiffness: 300, damping: 30 }}
        >
          <Circle
            size={8}
            className={clsx(
              "mt-1.5 shrink-0 rounded-full",
              STATUS_DOT[agent.status],
              (agent.status === "BLOCKED" || agent.status === "ERROR") && "shadow-[0_0_10px_currentColor]"
            )}
          />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[0.8125rem] font-semibold text-ink">{AGENT_LABEL[agent.name]}</span>
            <span className="truncate text-[0.6875rem] text-ink-muted">
              {STATUS_LABEL[agent.status]} &middot; {agent.current_task ?? "—"}
            </span>
          </div>
        </motion.div>
      ))}
    </TileGrid>
  );
}
