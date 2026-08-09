"use client";

// Order.co-style split-payment visual: ONE payment node on the left fanning
// out to the recipient (vendor / internal) nodes on the right, with animated
// flow along each path. Used in the plan panel (proposed order split) and the
// post-call outcome (agreed payment split). Pure presentation — every number
// arrives pre-computed.

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { IndianRupee, Package, Warehouse } from "lucide-react";
import clsx from "clsx";
import { formatPaiseFull, formatPaiseShort } from "@/lib/format";

export interface SplitRecipient {
  id: string;
  name: string;
  amount_paise: number;
  detail?: string;
  internal?: boolean;
}

interface PathSpec {
  d: string;
  id: string;
}

export default function PaymentSplitFlow({
  totalPaise,
  recipients,
  title = "One payment, split at source",
  note,
  compact = false,
}: {
  totalPaise: number;
  recipients: SplitRecipient[];
  title?: string;
  note?: string;
  compact?: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [paths, setPaths] = useState<PathSpec[]>([]);

  useEffect(() => {
    function measure() {
      const container = containerRef.current;
      if (!container) return;
      const containerRect = container.getBoundingClientRect();
      const fromEl = container.querySelector('[data-split-node="source"]');
      if (!fromEl) return;
      const fromRect = fromEl.getBoundingClientRect();
      const from = {
        x: fromRect.right - containerRect.left,
        y: fromRect.top - containerRect.top + fromRect.height / 2,
      };
      const next: PathSpec[] = [];
      for (const r of recipients) {
        const toEl = container.querySelector(`[data-split-node="r-${r.id}"]`);
        if (!toEl) continue;
        const toRect = toEl.getBoundingClientRect();
        const to = { x: toRect.left - containerRect.left, y: toRect.top - containerRect.top + toRect.height / 2 };
        const midX = (from.x + to.x) / 2;
        next.push({ id: r.id, d: `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}` });
      }
      setPaths(next);
    }
    const timeout = setTimeout(measure, 60);
    window.addEventListener("resize", measure);
    return () => {
      clearTimeout(timeout);
      window.removeEventListener("resize", measure);
    };
  }, [recipients]);

  const shares = recipients.map((r) => (totalPaise > 0 ? Math.round((r.amount_paise / totalPaise) * 100) : 0));

  return (
    <div className={clsx("rounded-lg border border-line bg-surface-2/40", compact ? "p-3" : "p-4")}>
      <p className="eyebrow mb-3">{title}</p>
      <div ref={containerRef} className="relative flex items-center gap-10">
        {/* Source: the single payment */}
        <div
          data-split-node="source"
          className="relative z-10 w-[170px] shrink-0 rounded-lg border border-accent/40 bg-surface p-3 shadow-sm"
        >
          <div className="mb-1 flex items-center gap-1.5 text-accent">
            <IndianRupee size={13} />
            <span className="text-[10px] font-semibold tracking-wide uppercase">One payment</span>
          </div>
          <p className={clsx("numeric font-semibold text-ink", compact ? "text-lg" : "text-xl")}>
            {formatPaiseFull(totalPaise)}
          </p>
          <p className="mt-0.5 text-[10.5px] text-ink-faint">debited once from the business</p>
        </div>

        {/* Animated fan-out paths */}
        <svg className="pointer-events-none absolute inset-0 z-0 h-full w-full overflow-visible">
          {paths.map((p, i) => (
            <g key={p.id}>
              <motion.path
                d={p.d}
                fill="none"
                stroke="var(--color-accent, #4d80b8)"
                strokeWidth={1.5}
                opacity={0.45}
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.7, delay: 0.15 * i, ease: "easeOut" }}
              />
              {/* travelling pulse — reads as money moving */}
              <circle r={3} fill="var(--color-accent, #4d80b8)" opacity={0.9}>
                <animateMotion dur="2.2s" begin={`${0.4 + 0.3 * i}s`} repeatCount="indefinite" path={p.d} />
              </circle>
            </g>
          ))}
        </svg>

        {/* Recipients */}
        <div className="relative z-10 flex min-w-0 flex-1 flex-col gap-2">
          {recipients.map((r, i) => (
            <motion.div
              key={r.id}
              data-split-node={`r-${r.id}`}
              initial={{ opacity: 0, x: 24 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.2 + 0.15 * i, ease: "easeOut" }}
              className={clsx(
                "flex items-center justify-between gap-3 rounded-md border px-3 py-2",
                r.internal ? "border-info/30 bg-info/5" : "border-line bg-surface"
              )}
            >
              <div className="flex min-w-0 items-center gap-2">
                {r.internal ? (
                  <Warehouse size={14} className="shrink-0 text-info" />
                ) : (
                  <Package size={14} className="shrink-0 text-ink-faint" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-[12.5px] font-medium text-ink">{r.name}</p>
                  {r.detail && <p className="truncate text-[10.5px] text-ink-faint">{r.detail}</p>}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <p className="numeric text-[13px] font-semibold text-ink">{formatPaiseShort(r.amount_paise)}</p>
                <p className="numeric text-[10px] text-ink-faint">{shares[i]}%</p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
      {note && <p className="mt-2.5 text-[10.5px] text-ink-faint">{note}</p>}
    </div>
  );
}
