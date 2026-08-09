"use client";

import { useMemo } from "react";
import Link from "next/link";
import clsx from "clsx";
import { ArrowRight } from "lucide-react";
import {
  useAgentsStatus,
  useBusinessProfile,
  useDashboardSummary,
  useDisruptions,
  useSettlementBatches,
  useVendors,
} from "@/lib/queries";
import type { AgentName, AgentState, AgentStatusValue, DisruptionStage } from "@/lib/types";
import PageHeader from "@/components/PageHeader";
import Badge from "@/components/ui/badge";
import Skeleton from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";

interface StageDef {
  id: string;
  title: string;
  /** One sentence, written for someone who has never seen the demo. */
  what: string;
  /** Display name of whatever owns the step. `agent` is set only when that
   *  owner is a real entry in the agent mesh — the ingest parser is
   *  deterministic Python with no live status to report, and pretending
   *  otherwise would put a status dot next to something that has no status. */
  owner: { label: string; agent?: AgentName };
  /** Backend stages whose live rows belong to this step. Empty for Onboard,
   *  which is counted off the business profile rather than the disruption
   *  table — nothing has been disrupted yet at that point. */
  stages: DisruptionStage[];
  /** What the headline figure counts, in the reader's words. */
  unit: string;
  href?: string;
  linkLabel?: string;
  /** The state machine refuses these transitions unless the actor is a human
   *  (backend engine.py's HUMAN_ONLY_TRANSITIONS). It is the only honest way
   *  to say which steps wait on a person and which just happen. */
  humanGate?: boolean;
}

const STAGES: StageDef[] = [
  {
    id: "onboard",
    title: "Onboard",
    what: "You hand over the spreadsheets you already keep. The parser reads them into vendors, items and purchase orders, so every step below has something real to watch.",
    owner: { label: "Ingest parser" },
    stages: [],
    unit: "vendors on file",
    href: "/onboarding",
    linkLabel: "Add data sources",
  },
  {
    id: "detect",
    title: "Detect",
    what: "Sentinel watches every open order for the failures that arrive quietly — a delivery slipping past its date, a vendor going silent, stock heading for a stockout.",
    owner: { label: "Sentinel", agent: "SENTINEL" },
    stages: ["DETECTED"],
    unit: "just detected",
    href: "/waterfall",
    linkLabel: "See what's been caught",
  },
  {
    id: "diagnose",
    title: "Diagnose",
    what: "Diagnosis works out the root cause and prices the damage — blocked order value, contract penalties, idle line time — then explains it against that evidence, never against a guess.",
    owner: { label: "Diagnosis", agent: "DIAGNOSIS" },
    stages: ["DIAGNOSED"],
    unit: "being quantified",
  },
  {
    id: "source",
    title: "Source",
    what: "Sourcing ranks alternates in the same category on reliability, lead time, price and distance, and verifies each one's GSTIN before it is ever offered to you.",
    owner: { label: "Sourcing", agent: "SOURCING" },
    stages: ["SOURCING"],
    unit: "finding alternates",
    href: "/vendors",
    linkLabel: "Browse the vendor network",
  },
  {
    id: "approve",
    title: "Approve",
    what: "Nothing switches vendor on its own. The plan reaches the owner on WhatsApp as a card carrying the number, and the pipeline stops dead until a person answers it.",
    owner: { label: "Governance", agent: "GOVERNANCE" },
    stages: ["AWAITING_APPROVAL"],
    unit: "waiting on you",
    href: "/",
    linkLabel: "Open the approval queue",
    humanGate: true,
  },
  {
    id: "negotiate",
    title: "Negotiate",
    what: "Once approved, the voice agent calls the alternate vendor in their own language, holds the price and lead-time guardrails, and comes back with terms rather than a transcript to read.",
    owner: { label: "Negotiation", agent: "NEGOTIATION" },
    stages: ["NEGOTIATING", "NEGOTIATED"],
    unit: "on call or agreed",
  },
  {
    id: "settle",
    title: "Settle",
    what: "Everything agreed across the month collects into one payout batch. You confirm it, the transaction agent executes it, and the vendors are paid in a single movement instead of a dozen.",
    owner: { label: "Settlement", agent: "SETTLEMENT" },
    stages: ["SETTLEMENT_PENDING", "SETTLED"],
    unit: "in settlement",
    href: "/settlement",
    linkLabel: "Open transactions",
    humanGate: true,
  },
];

const AGENT_DOT: Record<AgentStatusValue, string> = {
  IDLE: "bg-neutral",
  RUNNING: "bg-info animate-blink",
  DONE: "bg-success",
  BLOCKED: "bg-critical animate-blink",
  ERROR: "bg-critical animate-blink",
};

const AGENT_STATUS_LABEL: Record<AgentStatusValue, string> = {
  IDLE: "Idle",
  RUNNING: "Running",
  DONE: "Done",
  BLOCKED: "Blocked",
  ERROR: "Error",
};

/** The owner line: who runs this step, and — when it is an agent — what that
 *  agent is doing right now. The live note is what turns "agent mesh" from a
 *  slide word into something the reader can watch tick over. */
function OwnerLine({ owner, agent }: { owner: StageDef["owner"]; agent?: AgentState }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span
        className={clsx("size-1.5 shrink-0 rounded-full", agent ? AGENT_DOT[agent.status] : "bg-line-strong")}
        aria-hidden
      />
      <span className="eyebrow shrink-0">{owner.label}</span>
      {agent && (
        <>
          <span className="shrink-0 text-[11px] text-ink-faint">{AGENT_STATUS_LABEL[agent.status]}</span>
          {agent.current_task && (
            <span className="truncate text-[11px] text-ink-faint" title={agent.current_task}>
              · {agent.current_task}
            </span>
          )}
        </>
      )}
    </div>
  );
}

export default function PipelinePage() {
  const { data: summary, isPending: summaryPending } = useDashboardSummary();
  const { data: disruptions, isPending: disruptionsPending } = useDisruptions();
  const { data: profile, isPending: profilePending } = useBusinessProfile();
  const { data: agentsResponse } = useAgentsStatus();
  const { data: vendors, isPending: vendorsPending } = useVendors();
  const { data: batches } = useSettlementBatches();

  // The dashboard summary is the preferred source — it counts server-side and
  // is already refetched on a timer. The disruption list is only a fallback for
  // when that request hasn't landed (or failed), so the page still shows real
  // counts instead of a permanent skeleton.
  const stageCounts = useMemo(() => {
    const counts = new Map<DisruptionStage, number>();
    if (summary) {
      for (const entry of summary.stage_counts) counts.set(entry.stage, entry.count);
    } else {
      for (const item of disruptions?.items ?? []) counts.set(item.stage, (counts.get(item.stage) ?? 0) + 1);
    }
    return counts;
  }, [summary, disruptions]);

  const agentByName = useMemo(
    () => new Map((agentsResponse?.agents ?? []).map((a) => [a.name, a])),
    [agentsResponse]
  );

  const countsPending = summaryPending && disruptionsPending;
  // The business profile is the intended source for step one, but it only
  // exists once ingest has assembled one; the vendor list is the same
  // quantity from an endpoint that answers either way, so a missing profile
  // degrades to a smaller claim rather than a contradictory zero.
  const vendorCount = profile?.vendor_count ?? vendors?.total ?? 0;
  const itemCount = profile?.item_count ?? 0;
  const onboardPending = profilePending && vendorsPending;
  const disruptionTotal = summary
    ? summary.stage_counts.reduce((sum, entry) => sum + entry.count, 0)
    : (disruptions?.total ?? 0);

  // "Nothing ingested yet" is a real product state, not an error: the whole
  // screen then reads as a preview of what is about to happen. It needs at
  // least one answered request behind it, though — with the API unreachable,
  // silence is not the same as an empty workspace.
  const hasAnyData = Boolean(summary || disruptions || profile || vendors || batches);
  const isFresh =
    hasAnyData && !countsPending && !onboardPending && vendorCount === 0 && itemCount === 0 && disruptionTotal === 0;

  const rows = STAGES.map((stage, index) => {
    const count = stage.stages.length
      ? stage.stages.reduce((sum, s) => sum + (stageCounts.get(s) ?? 0), 0)
      : vendorCount;
    const pending = stage.stages.length ? countsPending : onboardPending;
    let note: string | null = null;
    if (stage.id === "onboard" && profile) note = `${itemCount} items parsed`;
    // Skipped when it would just echo step one's figure back — two identical
    // numbers on one screen read as a bug, not as context.
    if (stage.id === "source" && vendors && vendors.total !== vendorCount)
      note = `${vendors.total} vendors in the network`;
    if (stage.id === "settle" && batches) note = `${batches.total} payout ${batches.total === 1 ? "batch" : "batches"}`;
    return { stage, index, count, pending, note, live: !isFresh && count > 0 };
  });

  // The spine is lit as far as work has actually reached, which is the one
  // thing a static diagram of this flow can never tell you.
  const deepestLive = rows.reduce((deepest, row) => (row.live ? row.index : deepest), -1);

  const exposureTotalPaise = (summary?.exposure_at_risk_paise ?? 0) + (summary?.exposure_mitigated_paise ?? 0);
  const mitigatedPct = exposureTotalPaise > 0 ? Math.round(((summary?.exposure_mitigated_paise ?? 0) / exposureTotalPaise) * 100) : 0;

  return (
    <div>
      <PageHeader
        title="How it works"
        subtitle="Seven steps, from the spreadsheet you hand over to the payout that closes the month. Each one says what happens, which agent owns it, and how much is sitting in it right now."
      />

      {/* The through-line. Every step below exists to move rupees from the
          left figure to the right one, so it is stated once, at the top,
          rather than implied seven times. */}
      {countsPending ? (
        <Skeleton className="mb-6 h-[168px]" />
      ) : isFresh ? (
        <section className="panel mb-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-4 p-5">
          <div className="max-w-2xl">
            <h2 className="font-display text-[16px] font-bold tracking-[-0.01em] text-ink">Nothing has been ingested yet</h2>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-muted">
              The seven steps below are what happens once there is data to watch. Sentinel can only see the orders it has
              been given, so everything starts with a spreadsheet.
            </p>
          </div>
          <Link href="/onboarding" className={buttonVariants({ size: "sm" })}>
            Add your first spreadsheet
            <ArrowRight size={14} />
          </Link>
        </section>
      ) : (
        <section className="panel mb-6 p-5">
          <div className="grid grid-cols-1 items-center gap-x-6 gap-y-4 sm:grid-cols-[1fr_auto_1fr]">
            <div>
              <p className="eyebrow">Exposure at risk</p>
              <p className="numeric mt-2 text-[30px] leading-none font-semibold text-critical" data-numeric>
                {summary?.exposure_at_risk_display ?? "—"}
              </p>
              <p className="mt-2 text-[12px] text-ink-faint">
                <span className="numeric" data-numeric>
                  {summary?.active_disruptions ?? 0}
                </span>{" "}
                disruption{summary?.active_disruptions === 1 ? "" : "s"} still open
              </p>
            </div>

            <ArrowRight size={18} className="hidden shrink-0 text-ink-faint sm:block" aria-hidden />

            <div className="sm:text-right">
              <p className="eyebrow">Exposure mitigated</p>
              <p className="numeric mt-2 text-[30px] leading-none font-semibold text-success" data-numeric>
                {summary?.exposure_mitigated_display ?? "—"}
              </p>
              <p className="mt-2 text-[12px] text-ink-faint">
                <span className="numeric" data-numeric>
                  {summary?.disruptions_closed_today ?? 0}
                </span>{" "}
                closed out
              </p>
            </div>
          </div>

          {exposureTotalPaise > 0 && (
            <div
              className="mt-5 flex h-2 overflow-hidden rounded-full bg-critical-dim"
              role="img"
              aria-label={`${mitigatedPct}% of identified exposure has been mitigated`}
            >
              <span className="bg-success transition-[width] duration-500 ease-out" style={{ width: `${mitigatedPct}%` }} />
            </div>
          )}

          <p className="mt-3 text-[12px] leading-relaxed text-ink-muted">
            Every step below this line exists to move rupees from the left figure to the right one.
          </p>
        </section>
      )}

      <p className="mb-4 max-w-3xl text-[12px] leading-relaxed text-ink-faint">
        A step on a white card has work sitting in it right now, and the spine is lit as far as work has reached. Two
        steps carry a <span className="font-semibold text-ink-muted">Needs you</span> tag — those are the transitions
        the system refuses to make without a person.
      </p>

      <ol className="mb-2">
        {rows.map(({ stage, index, count, pending, note, live }) => {
          const agent = stage.owner.agent ? agentByName.get(stage.owner.agent) : undefined;
          const isLast = index === rows.length - 1;
          const litInto = index <= deepestLive;
          const litOut = index < deepestLive;

          return (
            <li key={stage.id} className="grid grid-cols-[2.25rem_1fr] gap-x-4 sm:gap-x-5">
              {/* Spine: connector in, the step's number, connector out. The
                  trailing segment is flex-1 so it stretches through the card's
                  bottom padding and the line never breaks between steps. */}
              <div className="flex flex-col items-center" aria-hidden>
                <span
                  className={clsx(
                    "h-4 w-0.5 shrink-0 rounded-full",
                    index === 0 ? "bg-transparent" : litInto ? "bg-accent" : "bg-line"
                  )}
                />
                <span
                  className={clsx(
                    "numeric flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                    live
                      ? "bg-accent text-accent-ink"
                      : litInto
                        ? "bg-accent-dim text-accent"
                        : "bg-surface-3 text-ink-faint"
                  )}
                >
                  {index + 1}
                </span>
                <span
                  className={clsx("w-0.5 flex-1 rounded-full", isLast ? "bg-transparent" : litOut ? "bg-accent" : "bg-line")}
                />
              </div>

              <div className={clsx(!isLast && "pb-4")}>
                <article
                  className={clsx(
                    "p-5",
                    live ? "panel" : "rounded-lg border border-line bg-surface-2"
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                    <div className="min-w-[16rem] flex-1">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <h2 className="font-display text-[16px] leading-none font-bold tracking-[-0.01em] text-ink">
                          {stage.title}
                        </h2>
                        {stage.humanGate && (
                          <Badge tone="accent" dot={false}>
                            Needs you
                          </Badge>
                        )}
                      </div>
                      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-ink-muted">{stage.what}</p>
                    </div>

                    <div className="shrink-0 sm:text-right">
                      {pending ? (
                        <Skeleton className="h-7 w-16 sm:ml-auto" />
                      ) : (
                        <p
                          className={clsx(
                            "numeric text-[28px] leading-none font-semibold",
                            isFresh ? "text-ink-faint" : live ? "text-accent" : "text-ink-faint"
                          )}
                          data-numeric
                        >
                          {isFresh ? "—" : count}
                        </p>
                      )}
                      <p className="eyebrow mt-2">{stage.unit}</p>
                      {note && !isFresh && <p className="mt-1 text-[11px] text-ink-faint">{note}</p>}
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line pt-3">
                    <OwnerLine owner={stage.owner} agent={agent} />
                    {stage.href && (
                      <Link
                        href={stage.href}
                        className="shrink-0 rounded-sm text-[12px] font-medium text-ink-muted transition-colors duration-150 outline-offset-2 hover:text-accent focus-visible:text-accent"
                      >
                        {stage.linkLabel} →
                      </Link>
                    )}
                  </div>
                </article>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
