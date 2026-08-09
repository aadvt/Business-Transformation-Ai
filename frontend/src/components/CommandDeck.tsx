"use client";

import { useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  FileSpreadsheet,
  Paperclip,
  ReceiptText,
  Send,
  Sparkles,
  Wallet,
} from "lucide-react";
import clsx from "clsx";
import Link from "next/link";
import { useDashboardSummary, useDisruptions, useVendorDues } from "@/lib/queries";
import {
  PIPELINE_PHASES,
  isFailedStage,
  isTerminalStage,
  phaseIndexForStage,
  type DisruptionSummary,
} from "@/lib/types";

/* The deck is the only interactive layer floating over the live map. Every
   surface in here is glass for one reason: the map underneath moves, and a
   solid panel would either fight it for attention or hide the network the
   operator is trying to read. */

function severityOf(exposurePaise: number): "critical" | "elevated" | "moderate" {
  if (exposurePaise >= 10_00_00_000) return "critical";
  if (exposurePaise >= 25_00_000) return "elevated";
  return "moderate";
}

const SEVERITY_DOT = {
  critical: "bg-critical",
  elevated: "bg-warning",
  moderate: "bg-info",
} as const;

/* ---------------- Focus stepper ---------------- */

function FocusStepper({ disruption }: { disruption: DisruptionSummary | null }) {
  if (!disruption) return null;

  const activeIndex = phaseIndexForStage(disruption.stage);
  const failed = isFailedStage(disruption.stage);
  const settled = isTerminalStage(disruption.stage);

  return (
    <div className="pointer-events-auto flex flex-col items-center">
      <div className="mb-3 text-center">
        <h2 className="font-display text-[20px] leading-tight font-bold text-ink">
          {disruption.vendor.name}
        </h2>
        <Link
          href="/waterfall"
          className="glass mt-1.5 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[12px] transition-colors duration-150 hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span className="eyebrow">Exposure</span>
          <span className="numeric font-semibold text-ink">{disruption.exposure_total_display}</span>
        </Link>
      </div>

      <ol className="glass flex max-w-[min(92vw,860px)] items-start gap-1 overflow-x-auto px-6 py-4">
        {PIPELINE_PHASES.map((phase, index) => {
          const done = settled || index < activeIndex;
          const current = !settled && index === activeIndex;
          const errored = failed && index === activeIndex;

          return (
            <li key={phase.id} className="flex items-start gap-1">
              <div className="flex w-[74px] shrink-0 flex-col items-center gap-2">
                <span className="relative flex size-5 items-center justify-center">
                  {current && !errored && (
                    <span className="absolute inset-[-5px] animate-pulse rounded-full bg-accent/20" />
                  )}
                  <span
                    className={clsx(
                      "relative z-10 flex size-5 items-center justify-center rounded-full transition-colors duration-200",
                      errored && "bg-critical",
                      !errored && done && "bg-accent",
                      !errored && current && "border-2 border-accent bg-surface",
                      !errored && !done && !current && "border border-line-strong bg-surface"
                    )}
                  >
                    {errored ? (
                      <AlertTriangle size={11} className="text-accent-ink" />
                    ) : done ? (
                      <Check size={12} strokeWidth={3} className="text-accent-ink" />
                    ) : current ? (
                      <span className="size-2 rounded-full bg-accent" />
                    ) : null}
                  </span>
                </span>
                <span
                  className={clsx(
                    "text-center text-[10px] leading-tight font-semibold tracking-[0.06em] uppercase",
                    errored && "text-critical",
                    !errored && (done || current) ? "text-accent" : "text-ink-faint"
                  )}
                >
                  {phase.label}
                </span>
              </div>
              {index < PIPELINE_PHASES.length - 1 && (
                <span
                  className={clsx(
                    "mt-2.5 h-0.5 w-6 shrink-0 rounded-full transition-colors duration-200",
                    index < activeIndex ? "bg-accent" : "bg-line-strong"
                  )}
                />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ---------------- Bento tiles ---------------- */

function TileShell({
  label,
  icon: Icon,
  tone = "default",
  children,
}: {
  label: string;
  icon: typeof Wallet;
  tone?: "default" | "alert" | "accent";
  children: React.ReactNode;
}) {
  return (
    <section className="glass pointer-events-auto flex min-h-[168px] flex-col p-5">
      <header
        className={clsx(
          "mb-4 flex items-center gap-2",
          tone === "alert" ? "text-critical" : tone === "accent" ? "text-accent" : "text-ink-muted"
        )}
      >
        <Icon size={16} />
        <h3 className="eyebrow !text-current">{label}</h3>
      </header>
      {children}
    </section>
  );
}

function MetricRow({
  value,
  label,
  tone = "default",
  divider,
}: {
  value: string;
  label: string;
  tone?: "default" | "critical" | "accent";
  divider?: boolean;
}) {
  return (
    <div
      className={clsx(
        "flex items-baseline justify-between gap-3",
        divider && "border-b border-line/70 pb-2.5"
      )}
    >
      <span
        className={clsx(
          "numeric text-[17px] font-semibold",
          tone === "critical" ? "text-critical" : tone === "accent" ? "text-accent" : "text-ink"
        )}
      >
        {value}
      </span>
      <span className="eyebrow">{label}</span>
    </div>
  );
}

function AssistantTile() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [messages, setMessages] = useState<{ from: "system" | "you"; text: string }[]>([
    { from: "system", text: "Monitoring the supply network. Ask about a vendor, disruption, or shipment." },
  ]);
  const [fileName, setFileName] = useState<string | null>(null);

  function send() {
    const input = inputRef.current;
    const text = input?.value.trim();
    if (!text || !input) return;
    setMessages((current) => [
      ...current,
      { from: "you", text },
      { from: "system", text: "Added to the operations queue. Related network changes will surface here." },
    ]);
    input.value = "";
  }

  return (
    <section className="glass pointer-events-auto flex min-h-[168px] flex-col p-5">
      <header className="mb-3 flex items-center gap-2 text-accent">
        <Sparkles size={16} />
        <h3 className="eyebrow !text-current">Ops assistant</h3>
      </header>

      <div className="mb-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto text-[12px] leading-relaxed">
        {messages.slice(-3).map((message, index) => (
          <p
            key={index}
            className={clsx(
              "rounded-md px-2.5 py-1.5",
              message.from === "you"
                ? "ml-6 bg-accent text-accent-ink"
                : "mr-2 bg-surface/70 text-ink-muted"
            )}
          >
            {message.text}
          </p>
        ))}
        {fileName && (
          <p className="flex items-center gap-1.5 text-[11px] text-ink-faint">
            <FileSpreadsheet size={12} />
            <span className="truncate">{fileName}</span>
          </p>
        )}
      </div>

      <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 transition-colors duration-150 focus-within:border-accent">
        <label
          className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-sm text-ink-faint transition-colors duration-150 hover:bg-surface-2 hover:text-accent focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent"
          title="Attach an Excel or CSV extract"
        >
          <Paperclip size={14} />
          <input
            className="sr-only"
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={(event) => setFileName(event.target.files?.[0]?.name ?? null)}
          />
        </label>
        <input
          ref={inputRef}
          onKeyDown={(event) => event.key === "Enter" && send()}
          className="min-w-0 flex-1 bg-transparent text-[12px] text-ink outline-none placeholder:text-ink-faint"
          placeholder="Ask about the network…"
          aria-label="Ask the operations assistant"
        />
        <button
          onClick={send}
          aria-label="Send"
          className="flex size-7 shrink-0 items-center justify-center rounded-sm text-accent transition-colors duration-150 hover:bg-accent-dim focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <Send size={14} />
        </button>
      </div>
    </section>
  );
}

/* ---------------- Deck ---------------- */

/* The demo control bar is a fixed, env-gated overlay pinned to the bottom-left
   of the viewport. When it's on it would sit straight on top of the first two
   bento tiles, so the deck reserves its height — and only then, since the bar
   is absent in normal operation and a permanent gap there would be dead space. */
const DEMO_CONTROLS = process.env.NEXT_PUBLIC_DEMO_CONTROLS === "true";

export default function CommandDeck() {
  const { data: summary } = useDashboardSummary();
  const { data: disruptions, isPending: disruptionsPending } = useDisruptions();
  const { data: dues } = useVendorDues();

  const open = useMemo(
    () => (disruptions?.items ?? []).filter((d) => !isTerminalStage(d.stage) && !isFailedStage(d.stage)),
    [disruptions]
  );

  // The stepper follows the largest live exposure — the one disruption the
  // room should be looking at, not simply the newest.
  const focus = useMemo(
    () => [...open].sort((a, b) => b.exposure_total_paise - a.exposure_total_paise)[0] ?? null,
    [open]
  );

  const oldestDue = useMemo(
    () => (dues?.items ?? []).reduce((max, item) => Math.max(max, item.oldest_invoice_age_days), 0),
    [dues]
  );

  return (
    <div
      className={clsx(
        "pointer-events-none absolute inset-0 z-20 flex flex-col justify-between gap-6 p-6",
        DEMO_CONTROLS && "pb-[150px]"
      )}
    >
      <div className="flex justify-center pt-1">
        <FocusStepper disruption={focus} />
      </div>

      {/* Stacking four 168px tiles would overflow a phone inside the map's
          overflow-hidden frame and silently clip the last one, so below sm the
          bento becomes one swipeable row instead of a column. It takes pointer
          events only at that size — on desktop the gaps stay transparent to
          the map underneath. */}
      <div className="mx-auto flex w-full max-w-[1240px] snap-x gap-4 overflow-x-auto pb-1 max-sm:pointer-events-auto [&>*]:min-w-[262px] [&>*]:shrink-0 [&>*]:snap-start sm:grid sm:grid-cols-2 sm:overflow-visible sm:pb-0 sm:[&>*]:min-w-0 xl:grid-cols-4">
        <TileShell label="Global exposure" icon={Wallet}>
          <div className="flex flex-col gap-2.5">
            <MetricRow
              divider
              tone="critical"
              value={summary?.exposure_at_risk_display ?? "—"}
              label="At risk"
            />
            <MetricRow tone="accent" value={summary?.exposure_mitigated_display ?? "—"} label="Mitigated" />
          </div>
        </TileShell>

        <TileShell label="Active disruptions" icon={AlertTriangle} tone="alert">
          <div className="flex items-baseline gap-2.5">
            {/* Counted from the same list rendered underneath rather than the
                server aggregate, so the headline number can never contradict
                the names below it. */}
            <span className="numeric font-display text-[34px] leading-none font-bold text-critical">
              {disruptions ? open.length : (summary?.active_disruptions ?? 0)}
            </span>
            <span className="text-[12px] text-ink-muted">live</span>
          </div>
          <ul className="mt-3 space-y-1.5">
            {disruptionsPending
              ? [0, 1, 2].map((i) => (
                  <li key={i} className="flex items-center gap-2">
                    <span className="skeleton size-1.5 rounded-full" />
                    <span className="skeleton h-3 w-28" />
                  </li>
                ))
              : open.slice(0, 3).map((item) => (
                  <li key={item.id} className="flex items-center gap-2 text-[12px]">
                    <span
                      className={clsx(
                        "size-1.5 shrink-0 rounded-full",
                        SEVERITY_DOT[severityOf(item.exposure_total_paise)]
                      )}
                    />
                    <span className="truncate text-ink">{item.vendor.name}</span>
                  </li>
                ))}
            {/* "Clear" is only ever claimed once the list has actually arrived. */}
            {!disruptionsPending && open.length === 0 && (
              <li className="text-[12px] text-ink-faint">Network clear — no open disruptions.</li>
            )}
          </ul>
        </TileShell>

        <TileShell label="Vendor dues" icon={ReceiptText}>
          <div className="flex flex-col gap-2.5">
            <MetricRow
              divider
              value={summary?.vendors_dues_total_display ?? dues?.total_due_display ?? "—"}
              label="Total due"
            />
            <MetricRow
              value={oldestDue > 0 ? `${oldestDue} days` : "—"}
              label="Oldest"
              tone={oldestDue >= 45 ? "critical" : "default"}
            />
          </div>
        </TileShell>

        <AssistantTile />
      </div>
    </div>
  );
}
