"use client";

import Link from "next/link";
import clsx from "clsx";
import { PIPELINE_PHASES, phaseIndexForStage } from "@/lib/types";
import type { AgentName, AgentState, AgentStatusValue, DisruptionSummary, PipelinePhaseId } from "@/lib/types";
import { formatPaiseShort, formatTimeAgo } from "@/lib/format";

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

/** Exposure banding — the only thing on a card that carries colour. */
type Severity = "high" | "elevated" | "standard";

function severityFor(paise: number): Severity {
  const rupees = paise / 100;
  if (rupees >= 1_00_00_000) return "high";
  if (rupees >= 25_00_000) return "elevated";
  return "standard";
}

const SEVERITY_DOT: Record<Severity, string> = {
  high: "bg-critical",
  elevated: "bg-warning",
  standard: "bg-info",
};

const SEVERITY_TEXT: Record<Severity, string> = {
  high: "text-critical",
  elevated: "text-warning",
  standard: "text-accent",
};

const SEVERITY_TITLE: Record<Severity, string> = {
  high: "High exposure",
  elevated: "Elevated exposure",
  standard: "Standard exposure",
};

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
    <section className="mb-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <h2 className="text-[15px] font-semibold text-ink">Disruption pipeline</h2>
          <span className="text-xs text-ink-faint">
            Sensing → Diagnosis → Sourcing → Negotiation → Governance → Settlement
          </span>
        </div>
        <Link
          href="/waterfall"
          className="rounded-sm text-xs text-ink-muted transition-colors duration-150 hover:text-accent focus-visible:text-accent"
        >
          Detailed view →
        </Link>
      </div>

      {/* Lanes are a tonal tray on the page field; the cards inside them are the
          only white surfaces, so depth reads as one step, never two. */}
      <div className="grid auto-cols-[minmax(232px,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
        {columns.map(({ phase, items, exposurePaise, agent }) => (
          <div key={phase.id} className="flex flex-col rounded-xl bg-surface-2 p-2">
            <div className="px-2 pt-1.5 pb-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="truncate text-[13px] font-semibold text-ink">{phase.label}</h3>
                <span
                  className="numeric shrink-0 rounded-full bg-surface-4 px-2 py-0.5 text-[11px] font-medium text-ink-muted"
                  data-numeric
                  title={`${items.length} disruption${items.length === 1 ? "" : "s"}`}
                >
                  {items.length}
                </span>
              </div>

              <div className="mt-2 flex items-center justify-between gap-2">
                <span
                  className="flex min-w-0 items-center gap-1.5"
                  title={agent ? AGENT_TITLE[agent.status] : undefined}
                >
                  <span
                    className={clsx(
                      "h-1.5 w-1.5 shrink-0 rounded-full",
                      agent ? AGENT_DOT[agent.status] : "bg-neutral"
                    )}
                  />
                  <span className="eyebrow truncate">{PHASE_AGENT[phase.id]}</span>
                </span>
                <span className="numeric shrink-0 text-[11px] text-ink-muted" data-numeric>
                  {exposurePaise > 0 ? formatPaiseShort(exposurePaise) : "—"}
                </span>
              </div>
            </div>

            <div className="flex flex-1 flex-col gap-2">
              {items.length === 0 ? (
                <p className="rounded-md border border-dashed border-line px-2 py-5 text-center text-[11px] text-ink-faint">
                  Empty
                </p>
              ) : (
                items.map((d) => {
                  const severity = severityFor(d.exposure_total_paise);
                  return (
                    <article
                      key={d.id}
                      className="shadow-panel rounded-md border border-line bg-surface p-3 transition-colors duration-150 hover:border-line-strong"
                      title={d.headline}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h4 className="truncate text-[11px] font-semibold tracking-[0.04em] text-ink uppercase">
                          {d.vendor.name}
                        </h4>
                        <span
                          className={clsx("mt-1 h-2 w-2 shrink-0 rounded-full", SEVERITY_DOT[severity])}
                          title={SEVERITY_TITLE[severity]}
                        />
                      </div>

                      <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-ink-muted">{d.headline}</p>

                      <div className="mt-2.5 flex items-baseline justify-between gap-2 border-t border-line pt-2">
                        <span className={clsx("numeric text-xs font-semibold", SEVERITY_TEXT[severity])} data-numeric>
                          {d.exposure_total_display}
                        </span>
                        <span
                          className="shrink-0 text-[10px] whitespace-nowrap text-ink-faint"
                          title={`Detected ${formatTimeAgo(d.detected_at)}`}
                        >
                          {formatTimeAgo(d.detected_at)}
                        </span>
                      </div>
                    </article>
                  );
                })
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
