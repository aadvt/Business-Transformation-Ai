"use client";

import { LayoutGroup, motion, useReducedMotion } from "framer-motion";
import { Ruler, TrendingUp, type LucideIcon } from "lucide-react";
import clsx from "clsx";
import type { DetectorSource, DisruptionStage, DisruptionSummary } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import Skeleton from "./ui/skeleton";
import StatusTag from "./StatusTag";
import { EmptyState } from "./PageHeader";

type LaneId = "awaiting_approval" | "negotiating" | "in_progress" | "settlement_pending" | "closed" | "failed";

/* The lane a stage sits in — the page's old STAGE_RANK map with the ranks
   named, so the bucketing is unchanged. Typed as a complete Record so a stage
   added to the enum fails to compile until it has been given a lane, rather
   than silently dropping off the board. */
const LANE_OF_STAGE: Record<DisruptionStage, LaneId> = {
  AWAITING_APPROVAL: "awaiting_approval",
  NEGOTIATING: "negotiating",
  NEGOTIATED: "negotiating",
  DETECTED: "in_progress",
  DIAGNOSED: "in_progress",
  SOURCING: "in_progress",
  APPROVED: "in_progress",
  SETTLEMENT_PENDING: "settlement_pending",
  SETTLED: "closed",
  CLOSED: "closed",
  REJECTED: "failed",
  FAILED: "failed",
};

interface LaneDef {
  id: LaneId;
  label: string;
  /* On a single-stage lane the header dot is the card's only status colour,
     so it has to carry the lane's meaning rather than decorate it. */
  dot: string;
}

// Left-to-right in the order STAGE_RANK ranked them: the lanes that need a
// human first, the terminal ones last. Failures sit at the end but are never
// collapsed away — an unsurfaced failure is the one that costs money.
const LANES: LaneDef[] = [
  { id: "awaiting_approval", label: "Awaiting approval", dot: "bg-critical" },
  { id: "negotiating", label: "Negotiating", dot: "bg-accent" },
  { id: "in_progress", label: "In progress", dot: "bg-info" },
  { id: "settlement_pending", label: "Settlement pending", dot: "bg-accent" },
  { id: "closed", label: "Closed", dot: "bg-success" },
  { id: "failed", label: "Failed / rejected", dot: "bg-critical" },
];

/* A lane holding more than one stage cannot be read as the stage itself, so
   its cards carry a StatusTag; on a single-stage lane the tag would only
   repeat the header. Derived from the map above rather than flagged by hand,
   so the two cannot drift apart. */
const MULTI_STAGE_LANES: ReadonlySet<LaneId> = (() => {
  const counts = new Map<LaneId, number>();
  for (const lane of Object.values(LANE_OF_STAGE)) counts.set(lane, (counts.get(lane) ?? 0) + 1);
  return new Set([...counts].filter(([, n]) => n > 1).map(([lane]) => lane));
})();

/* The same bands `severityForExposurePaise` applies on the map (NetworkMap.tsx)
   and PipelineBoard: ≥₹1Cr critical, ≥₹25L elevated, moderate below that.
   Re-stated here rather than imported because NetworkMap drags in three.js and
   mapbox-gl — one shared threshold is not worth that bundle on this route. */
type Severity = "critical" | "elevated" | "moderate";

function severityForExposurePaise(paise: number): Severity {
  const rupees = paise / 100;
  if (rupees >= 1_00_00_000) return "critical";
  if (rupees >= 25_00_000) return "elevated";
  return "moderate";
}

const SEVERITY_TEXT: Record<Severity, string> = {
  critical: "text-critical",
  elevated: "text-warning",
  moderate: "text-accent",
};

const SEVERITY_TITLE: Record<Severity, string> = {
  critical: "Critical exposure — ₹1Cr or above",
  elevated: "Elevated exposure — ₹25L or above",
  moderate: "Moderate exposure",
};

/* Whether a model or a rule raised the disruption changes how much an operator
   should trust the headline, so it earns a mark — small, at the card's edge. */
const DETECTOR: Record<DetectorSource, { icon: LucideIcon; label: string }> = {
  TTM_FORECAST: { icon: TrendingUp, label: "Raised by the TTM forecast model" },
  RULE_BASED: { icon: Ruler, label: "Raised by a threshold rule" },
};

// Lanes are equal-width tracks that overflow into a horizontal scroll rather
// than compressing — six readable lanes beat six unreadable ones.
const BOARD_GRID = "grid auto-cols-[minmax(244px,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2";

// A tonal tray on the page field; the cards inside are the only white surfaces,
// so depth reads as one step, never two.
const LANE_TRAY = "flex flex-col rounded-xl bg-surface-2 p-2";

function LaneHeader({ lane, count }: { lane: LaneDef; count?: number }) {
  return (
    <div className="flex items-center justify-between gap-2 px-2 pt-1.5 pb-3">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className={clsx("size-1.5 shrink-0 rounded-full", lane.dot)} />
        <h3 className="truncate text-[13px] font-semibold text-ink">{lane.label}</h3>
      </div>
      {count === undefined ? (
        <Skeleton className="h-[18px] w-7 rounded-full" />
      ) : (
        <span
          className="numeric shrink-0 rounded-full bg-surface-4 px-2 py-0.5 text-[11px] font-medium text-ink-muted"
          data-numeric
          title={`${count} disruption${count === 1 ? "" : "s"}`}
        >
          {count}
        </span>
      )}
    </div>
  );
}

function UpdateCard({
  disruption,
  showStage,
  dimmed,
  reducedMotion,
}: {
  disruption: DisruptionSummary;
  showStage: boolean;
  dimmed: boolean;
  reducedMotion: boolean;
}) {
  const severity = severityForExposurePaise(disruption.exposure_total_paise);
  const detector = DETECTOR[disruption.detector_source];
  const DetectorIcon = detector.icon;

  return (
    <motion.article
      // A stage change moves a card to a different lane, which is a different
      // DOM position — `layoutId` is what lets framer treat the two as one
      // element and travel between them instead of popping.
      layout={!reducedMotion}
      layoutId={disruption.id}
      transition={reducedMotion ? { duration: 0 } : { type: "spring", stiffness: 340, damping: 32, mass: 0.6 }}
      className={clsx(
        "shadow-panel rounded-md border border-line bg-surface p-3 transition-colors duration-150 hover:border-line-strong",
        dimmed && "opacity-70"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h4 className="truncate text-[12px] font-semibold text-ink" title={disruption.vendor.name}>
          {disruption.vendor.name}
        </h4>
        <span className="mt-px shrink-0 text-ink-faint" title={detector.label}>
          <DetectorIcon size={12} aria-hidden />
          <span className="sr-only">{detector.label}</span>
        </span>
      </div>

      <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-ink-muted" title={disruption.headline}>
        {disruption.headline}
      </p>

      {showStage && (
        <div className="mt-2">
          <StatusTag stage={disruption.stage} />
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 border-t border-line pt-2">
        <span
          className={clsx("numeric text-[12px] font-semibold", SEVERITY_TEXT[severity])}
          data-numeric
          title={SEVERITY_TITLE[severity]}
        >
          {disruption.exposure_total_display}
        </span>
        {/* DisruptionSummary carries `detected_at` and nothing else — per-stage
            timestamps live on the full Disruption's timeline, which the list
            endpoint does not return. So this is age since detection; it is not
            and must not be read as time spent in this lane. */}
        <span className="shrink-0 text-[10px] whitespace-nowrap text-ink-faint">
          Detected {formatTimeAgo(disruption.detected_at)}
        </span>
      </div>
    </motion.article>
  );
}

function BoardSkeleton() {
  return (
    <div className={BOARD_GRID} aria-busy>
      {LANES.map((lane) => (
        <div key={lane.id} className={LANE_TRAY}>
          {/* Lane labels are static, so they can be real while the counts and
              cards are still loading — nothing shifts when the data lands. */}
          <LaneHeader lane={lane} />
          <div className="flex flex-col gap-2">
            <Skeleton className="h-[88px]" />
            <Skeleton className="h-[88px]" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function UpdatesBoard({
  disruptions,
  isLoading = false,
}: {
  disruptions: DisruptionSummary[];
  isLoading?: boolean;
}) {
  // framer-motion animates transforms in JS, so globals.css's reduced-motion
  // rule (which only neutralises CSS transitions) cannot reach these.
  const reducedMotion = useReducedMotion() ?? false;

  if (isLoading) return <BoardSkeleton />;
  if (disruptions.length === 0) return <EmptyState>Nothing in the pipeline right now.</EmptyState>;

  const byLane = new Map<LaneId, DisruptionSummary[]>(LANES.map((lane) => [lane.id, []]));
  // Newest first inside a lane — the same secondary sort the stacked view used.
  for (const d of [...disruptions].sort(
    (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
  )) {
    byLane.get(LANE_OF_STAGE[d.stage])?.push(d);
  }

  return (
    <LayoutGroup id="updates-board">
      <div className={BOARD_GRID}>
        {LANES.map((lane) => {
          const items = byLane.get(lane.id) ?? [];
          return (
            <div key={lane.id} className={LANE_TRAY}>
              <LaneHeader lane={lane} count={items.length} />
              {/* A lane that outgrows the viewport scrolls inside itself; the
                  board must never become one tall page again. */}
              <div className="flex max-h-[62vh] flex-1 flex-col gap-2 overflow-y-auto">
                {items.length === 0 ? (
                  <p className="rounded-md border border-dashed border-line px-2 py-5 text-center text-[11px] text-ink-faint">
                    Empty
                  </p>
                ) : (
                  items.map((d) => (
                    <UpdateCard
                      key={d.id}
                      disruption={d}
                      showStage={MULTI_STAGE_LANES.has(lane.id)}
                      // Closed work is kept on the board for context but should
                      // not compete with the lanes that still need someone.
                      dimmed={lane.id === "closed"}
                      reducedMotion={reducedMotion}
                    />
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
