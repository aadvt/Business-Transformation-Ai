"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import type { ImpactGraph } from "@/lib/types";
import { EXPOSURE_COUNT_UP_MS } from "./graphVisuals";

const TIER_TONE: Record<string, string> = {
  HIGH: "text-critical",
  CRITICAL: "text-critical",
  MEDIUM: "text-warning",
  ELEVATED: "text-warning",
  LOW: "text-success",
  MODERATE: "text-info",
};

// Counts a rupee figure up from 0 rather than popping it in — reads well
// from the back of a room. Formats with the same locale/grouping as the
// backend's own `_display` strings so mid-count frames don't look broken.
function useCountUpPaise(targetPaise: number, active: boolean, durationMs: number): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!active) return;
    let raf: number;
    const start = performance.now();
    function tick(now: number) {
      const t = Math.min((now - start) / durationMs, 1);
      const eased = 1 - (1 - t) * (1 - t); // easeOutQuad
      setValue(Math.round(targetPaise * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, targetPaise, durationMs]);

  return value;
}

function formatPaiseLike(paise: number, sampleDisplay: string): string {
  // Reuses the backend's own formatting where possible (₹ + Indian digit
  // grouping) without re-deriving the exact rounding rule it used for
  // `exposure_display` — this only needs to look right mid-count.
  const rupees = Math.round(paise / 100);
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  const symbol = sampleDisplay.trim().startsWith("₹") ? "₹" : "";
  return `${symbol}${formatted}`;
}

export default function SummaryPanel({ graph, visible }: { graph: ImpactGraph; visible: boolean }) {
  // This panel sits over the live canvas and also renders straight off an
  // IMPACT_COMPUTED websocket payload, so it must not be the thing that takes
  // the whole page down if a field is missing — fall back, don't throw.
  const summary = graph.summary;
  const displayedPaise = useCountUpPaise(summary.exposure_paise ?? 0, visible, EXPOSURE_COUNT_UP_MS);
  const tier = summary.tier ?? "—";
  const tone = TIER_TONE[tier.toUpperCase()] ?? "text-ink";

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={visible ? { opacity: 1, y: 0 } : { opacity: 0, y: -8 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="elevated pointer-events-none absolute top-4 right-4 w-64 rounded-lg p-4"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="eyebrow">Exposure</span>
        <span className={`rounded-sm bg-surface-3 px-1.5 py-px text-[10px] font-semibold tracking-wider uppercase ${tone}`}>
          {tier}
        </span>
      </div>
      <p className={`numeric mb-3 text-[26px] leading-none font-semibold tracking-tight ${tone}`}>
        {formatPaiseLike(displayedPaise, summary.exposure_display ?? "₹")}
      </p>
      <div className="flex items-center gap-4 border-t border-line pt-2.5 text-[11px] text-ink-muted">
        <div>
          <p className="numeric text-[15px] font-medium text-ink">{summary.impacted_node_count ?? 0}</p>
          <p>Impacted nodes</p>
        </div>
        <div>
          <p className="numeric text-[15px] font-medium text-ink">{summary.at_risk_order_count ?? 0}</p>
          <p>At-risk orders</p>
        </div>
      </div>
    </motion.div>
  );
}
