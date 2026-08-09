"use client";

import Link from "next/link";
import clsx from "clsx";
import { PIPELINE_PHASES, phaseIndexForStage } from "@/lib/types";
import type { AgentName, AgentState, AgentStatusValue, DisruptionSummary, PipelinePhaseId } from "@/lib/types";
import { formatPaiseShort } from "@/lib/format";

/** Each pipeline phase is owned by exactly one agent — showing the owner's
 *  live status in the column header is what turns a list of stages into an
 *  actual operations view. */
const PHASE_AGENT: Record<PipelinePhaseId, AgentName> = {
  sensing: "SENTINEL",
  diagnosis: "DIAGNOSIS",
  sourcing: "SOURCING",
  negotiation: "NEGOTIATION",
  governance: "GOVERNANCE",
  settlement: "SETTLEMENT",
};

const AGENT_DOT: Record<AgentStatusValue, string> = {
  IDLE: "bg-neutral",
  RUNNING: "bg-info animate-blink",
  DONE: "bg-success",
  BLOCKED: "bg-critical animate-blink",
  ERROR: "bg-critical animate-blink",
};

const AGENT_TITLE: Record<AgentStatusValue, string> = {
  IDLE: "Idle",
  RUNNING: "Running",
  DONE: "Done",
  BLOCKED: "Blocked",
  ERROR: "Error",
};

function severityBorder(paise: number): string {
  const rupees = paise / 100;
  if (rupees >= 1_00_00_000) return "border-l-critical";
  if (rupees >= 25_00_000) return "border-l-warning";
  return "border-l-info";
}

interface PipelineBoardProps {
  disruptions: DisruptionSummary[];
  agents: AgentState[];
}

export default function PipelineBoard({ disruptions, agents }: PipelineBoardProps) {
  const agentByName = new Map(agents.map((a) => [a.name, a]));

  const columns = PIPELINE_PHASES.map((phase, index) => {
    const items = disruptions.filter((d) => phaseIndexForStage(d.stage) === index);
    return {
      phase,
      items,
      exposurePaise: items.reduce((sum, d) => sum + d.exposure_total_paise, 0),
      agent: agentByName.get(PHASE_AGENT[phase.id]),
    };
  });

  return (
    <div className="panel-flush mb-6">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <div className="flex items-baseline gap-2.5">
          <h2 className="text-[13px] font-semibold text-ink">Disruption pipeline</h2>
          <span className="text-xs text-ink-faint">
            Sensing → Diagnosis → Sourcing → Negotiation → Governance → Settlement
          </span>
        </div>
        <Link href="/waterfall" className="text-xs text-ink-muted transition-colors duration-100 hover:text-accent">
          Detailed view →
        </Link>
      </div>

      {/* gap-px over a line-coloured background renders as hairline dividers
          without doubling borders where columns meet. */}
      <div className="grid grid-cols-6 gap-px overflow-x-auto bg-line max-[900px]:grid-cols-3 max-[560px]:grid-cols-2">
        {columns.map(({ phase, items, exposurePaise, agent }) => (
          <div key={phase.id} className="min-w-[150px] bg-surface">
            <div className="border-b border-line px-3 pt-2.5 pb-2">
              <div className="flex items-center justify-between gap-2">
                <span className="eyebrow">{phase.label}</span>
                <span
                  className="numeric text-xs text-ink"
                  data-numeric
                  title={`${items.length} disruption${items.length === 1 ? "" : "s"}`}
                >
                  {items.length}
                </span>
              </div>

              <div className="mt-1.5 flex items-center gap-1.5" title={agent ? AGENT_TITLE[agent.status] : undefined}>
                <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", agent ? AGENT_DOT[agent.status] : "bg-neutral")} />
                <span className="truncate text-[10px] text-ink-faint">{PHASE_AGENT[phase.id]}</span>
              </div>

              <p className="numeric mt-1.5 text-[11px] text-ink-muted" data-numeric>
                {exposurePaise > 0 ? formatPaiseShort(exposurePaise) : "—"}
              </p>
            </div>

            <div className="flex flex-col gap-1 p-1.5">
              {items.length === 0 ? (
                <p className="px-1.5 py-3 text-center text-[11px] text-ink-faint">Empty</p>
              ) : (
                items.map((d) => (
                  <div
                    key={d.id}
                    className={clsx(
                      "row-hover cursor-default rounded-sm border-l-2 bg-surface-2 px-2 py-1.5",
                      severityBorder(d.exposure_total_paise)
                    )}
                    title={d.headline}
                  >
                    <p className="truncate text-[11px] leading-tight font-medium text-ink">{d.vendor.name}</p>
                    <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-ink-faint">{d.headline}</p>
                    <p className="numeric mt-1 text-[10px] text-ink-muted" data-numeric>
                      {d.exposure_total_display}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
