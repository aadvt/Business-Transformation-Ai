"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { formatPaiseFull } from "@/lib/format";
import type { Plan, PlanChangeDetail, PlanChangeKind, PlanRowItem } from "@/lib/types";

const KIND_LABEL: Record<PlanChangeKind, string> = {
  SPLIT_ORDER: "Split order",
  SWITCH_VENDOR: "Switch vendor",
  PULL_FORWARD_STOCK: "Internal",
  REDUCE_QUANTITY: "Reduce quantity",
  EXPEDITE_FREIGHT: "Expedite freight",
};

const KIND_TONE: Record<PlanChangeKind, string> = {
  SPLIT_ORDER: "bg-accent/12 text-accent",
  SWITCH_VENDOR: "bg-info/12 text-info",
  PULL_FORWARD_STOCK: "bg-neutral/15 text-ink-muted",
  REDUCE_QUANTITY: "bg-warning/12 text-warning",
  EXPEDITE_FREIGHT: "bg-warning/12 text-warning",
};

function useCountBetween(from: number, to: number, active: boolean, durationMs: number): number {
  const [value, setValue] = useState(from);
  useEffect(() => {
    if (!active) {
      setValue(from);
      return;
    }
    let raf: number;
    const start = performance.now();
    function tick(now: number) {
      const t = Math.min((now - start) / durationMs, 1);
      const eased = 1 - (1 - t) * (1 - t);
      setValue(Math.round(from + (to - from) * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, from, to, durationMs]);
  return value;
}

function RowCard({ row, internal, rowId }: { row: PlanRowItem; internal?: boolean; rowId: string }) {
  return (
    <div
      data-row-id={rowId}
      className={clsx("rounded-md border px-2.5 py-2", internal ? "border-info/30 bg-info/5" : "border-line bg-surface")}
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="truncate text-[12.5px] font-medium text-ink">{row.vendor_name}</p>
        {internal && <span className="rounded-sm bg-info/15 px-1.5 py-px text-[9px] font-semibold tracking-wide text-info uppercase">Internal</span>}
      </div>
      <p className="mb-1.5 text-[11.5px] text-ink-muted">{row.item}</p>
      <div className="numeric flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-faint">
        <span>{row.qty.toLocaleString("en-IN")} units</span>
        <span>{row.unit_price_display}</span>
        <span>{row.lead_time_days}d lead</span>
        <span>ETA {row.eta}</span>
      </div>
    </div>
  );
}

function DeltaBadges({ current, proposed }: { current: PlanRowItem; proposed: PlanRowItem }) {
  const qtyDelta = proposed.qty - current.qty;
  const leadDelta = proposed.lead_time_days - current.lead_time_days;
  const priceDelta = proposed.unit_price_paise - current.unit_price_paise;
  const badges: string[] = [];
  if (qtyDelta !== 0) badges.push(`${qtyDelta > 0 ? "+" : ""}${qtyDelta.toLocaleString("en-IN")} units`);
  if (leadDelta !== 0) badges.push(`${leadDelta > 0 ? "+" : ""}${leadDelta}d lead`);
  if (priceDelta !== 0) badges.push(`${priceDelta > 0 ? "+" : ""}${formatPaiseFull(priceDelta)}`);
  if (badges.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {badges.map((b) => (
        <span key={b} className="numeric rounded-sm bg-surface-2 px-1.5 py-px text-[10px] text-ink-muted">
          {b}
        </span>
      ))}
    </div>
  );
}

function ChangeBlock({ change }: { change: PlanChangeDetail }) {
  const [expanded, setExpanded] = useState(false);
  const isOneToOne = change.current.length === 1 && change.proposed.length === 1;

  return (
    <div className="rounded-lg border border-line bg-surface-2/40 p-2.5" data-change-id={change.id}>
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="mb-2 flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex items-center gap-2">
          <span className={clsx("rounded-sm px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase", KIND_TONE[change.kind])}>
            {KIND_LABEL[change.kind]}
          </span>
          <span className="text-[12.5px] text-ink">{change.description}</span>
        </div>
        <ChevronDown size={13} className={clsx("shrink-0 text-ink-faint transition-transform", expanded && "rotate-180")} />
      </button>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          {change.current.length === 0 ? (
            <p className="rounded-md border border-dashed border-line px-2.5 py-2 text-center text-[11px] text-ink-faint">No current line</p>
          ) : (
            change.current.map((row, i) => <RowCard key={i} row={row} rowId={`current-${change.id}-${i}`} />)
          )}
        </div>
        <div className="space-y-1.5">
          {change.proposed.map((row, i) => (
            <RowCard key={i} row={row} internal={change.kind === "PULL_FORWARD_STOCK"} rowId={`proposed-${change.id}-${i}`} />
          ))}
        </div>
      </div>

      {isOneToOne && <DeltaBadges current={change.current[0]} proposed={change.proposed[0]} />}

      {expanded && (
        <p className="mt-2.5 border-t border-line pt-2 text-[12px] leading-relaxed text-ink-muted">{change.rationale}</p>
      )}
    </div>
  );
}

interface ConnectorPath {
  d: string;
}

export default function PlanDiffPanel({ plan }: { plan: Plan }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [paths, setPaths] = useState<ConnectorPath[]>([]);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  const exposureAnimated = useCountBetween(plan.exposure_before_paise, plan.exposure_after_paise, visible, 900);

  useEffect(() => {
    function measure() {
      const container = containerRef.current;
      if (!container) return;
      const containerRect = container.getBoundingClientRect();
      const next: ConnectorPath[] = [];

      for (const change of plan.changes) {
        for (let ci = 0; ci < change.current.length; ci++) {
          const fromEl = container.querySelector(`[data-row-id="current-${change.id}-${ci}"]`);
          if (!fromEl) continue;
          const fromRect = fromEl.getBoundingClientRect();
          const from = { x: fromRect.right - containerRect.left, y: fromRect.top - containerRect.top + fromRect.height / 2 };

          for (let pi = 0; pi < change.proposed.length; pi++) {
            const toEl = container.querySelector(`[data-row-id="proposed-${change.id}-${pi}"]`);
            if (!toEl) continue;
            const toRect = toEl.getBoundingClientRect();
            const to = { x: toRect.left - containerRect.left, y: toRect.top - containerRect.top + toRect.height / 2 };
            const midX = (from.x + to.x) / 2;
            next.push({ d: `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}` });
          }
        }
      }
      setPaths(next);
    }

    const timeout = setTimeout(measure, 50);
    window.addEventListener("resize", measure);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("resize", measure);
    };
  }, [plan]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {plan.requires_escalation && (
        <div className="flex items-start gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2.5 text-[12.5px] text-warning">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>
            <strong className="font-semibold">Requires escalation.</strong> {plan.escalation_reason}
          </span>
        </div>
      )}

      <div className="border-b border-line px-4 py-3">
        <p className="text-[13.5px] text-ink">
          Exposure{" "}
          <span className="numeric font-semibold text-ink">{formatPaiseFull(exposureAnimated)}</span>
          {" → "}
          <span className="numeric font-semibold text-ink">{plan.exposure_after_display}</span>
          <span className="mx-2 text-ink-faint">·</span>
          Cost to resolve <span className="numeric font-medium text-ink">{plan.cost_to_resolve_display}</span>
          <span className="mx-2 text-ink-faint">·</span>
          Net saving <span className="numeric font-semibold text-success">{plan.net_saving_display}</span>
        </p>
      </div>

      <div ref={containerRef} className="relative flex-1 overflow-y-auto p-4">
        <div className="mb-2 grid grid-cols-2 gap-3">
          <p className="eyebrow">Current plan</p>
          <p className="eyebrow">Proposed plan</p>
        </div>

        <div className="relative space-y-3">
          {plan.changes.map((change) => (
            <ChangeBlock key={change.id} change={change} />
          ))}

          <svg className="pointer-events-none absolute inset-0 z-10 h-full w-full overflow-visible">
            {paths.map((p, i) => (
              <path key={i} d={p.d} fill="none" stroke="#4d80b8" strokeWidth={1.5} strokeDasharray="4 3" opacity={0.7} />
            ))}
          </svg>
        </div>
      </div>

      <div className="border-t border-line px-4 py-2 text-[11px] text-ink-faint">
        {plan.solver === "OR_TOOLS_CP_SAT"
          ? `Solved by OR-Tools CP-SAT in ${plan.solve_ms}ms`
          : `Solved by greedy fallback in ${plan.solve_ms}ms (CP-SAT unavailable)`}
      </div>
    </div>
  );
}
