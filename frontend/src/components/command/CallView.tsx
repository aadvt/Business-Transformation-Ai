"use client";

// D5b call mode. This is NOT a live transcript view — the Bolna agent is
// operated from an external dashboard and reports back only after the call
// ends. During the call the audience LISTENS; the screen shows what
// Sanjeevani told the agent before it dialed (the briefing panel). When the
// post-call webhook lands, the backend replays the completed call as
// CALL_TRANSCRIPT / CALL_FIELD_EXTRACTED / CALL_ENDED events (~7s reveal)
// and this view fills in truthfully (phase=POST_CALL_REVEAL).

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, AlertTriangle, PhoneCall, ShieldCheck, ShieldAlert } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { useLiveEvents } from "@/lib/live";
import { formatPaiseFull } from "@/lib/format";
import PaymentSplitFlow, { type SplitRecipient } from "./PaymentSplitFlow";
import Spinner from "@/components/ui/Spinner";
import { Button } from "@/components/ui/button";
import type {
  CallBriefingSnapshot,
  CallFieldValidation,
  CallGuardrails,
  CallSession,
  Plan,
  WSEventPayloads,
} from "@/lib/types";

const DEMO_CONTROLS = process.env.NEXT_PUBLIC_DEMO_CONTROLS === "true";
// If no webhook has arrived this long after the call started, surface the
// quiet waiting state (and the replay recovery behind demo controls).
const WEBHOOK_WAIT_TIMEOUT_MS = 90_000;
const CHAR_REVEAL_MS = 12;
const CHAR_REVEAL_CAP_MS = 900;

type EndedPayload = WSEventPayloads["CALL_ENDED"];

// ---- small pieces ----------------------------------------------------------

function Waveform({ active }: { active: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const bars = 28;
    const phases = Array.from({ length: bars }, () => Math.random() * Math.PI * 2);
    const speeds = Array.from({ length: bars }, () => 0.9 + Math.random() * 1.4);
    function draw(t: number) {
      if (!canvas || !ctx) return;
      const { width, height } = canvas;
      ctx.clearRect(0, 0, width, height);
      const barW = width / bars;
      for (let i = 0; i < bars; i++) {
        const amp = active ? 0.25 + 0.75 * Math.abs(Math.sin(t / 480 * speeds[i] + phases[i])) : 0.08;
        const h = Math.max(2, amp * height * 0.8);
        ctx.fillStyle = "rgba(69, 109, 91, 0.65)";
        ctx.fillRect(i * barW + barW * 0.25, (height - h) / 2, barW * 0.5, h);
      }
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active]);
  return <canvas ref={ref} width={200} height={44} className="h-11 w-full" aria-hidden />;
}

function CallTimer({ startedAt, stopped }: { startedAt: string; stopped: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (stopped) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [stopped]);
  const secs = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  return <p className="numeric text-2xl font-semibold text-ink">{mm}:{ss}</p>;
}

/** Character-by-character reveal, capped so long turns don't drag. */
function TypeText({ text }: { text: string }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    setCount(0);
    const perChar = Math.min(CHAR_REVEAL_MS, CHAR_REVEAL_CAP_MS / Math.max(text.length, 1));
    const id = setInterval(() => {
      setCount((c) => {
        if (c >= text.length) {
          clearInterval(id);
          return c;
        }
        return c + 1;
      });
    }, perChar);
    return () => clearInterval(id);
  }, [text]);
  return <span>{text.slice(0, count)}</span>;
}

const FIELD_ROWS: { key: string; label: string }[] = [
  { key: "availability_confirmed", label: "Availability" },
  { key: "quantity", label: "Quantity" },
  { key: "unit_price", label: "Unit price" },
  { key: "delivery_date", label: "Delivery date" },
  { key: "payment_terms_days", label: "Payment terms" },
  { key: "upi_id", label: "UPI ID" },
];

function fieldDisplay(key: string, f: CallFieldValidation): string {
  if (f.value === null || f.value === undefined || f.value === "") return "—";
  if (key === "unit_price" && typeof f.value === "number") return `${formatPaiseFull(f.value)}/unit`;
  if (key === "availability_confirmed") return f.value ? "Confirmed" : "Not confirmed";
  if (key === "payment_terms_days") return f.value === 0 ? "On delivery" : `${f.value} days`;
  if (key === "quantity" && typeof f.value === "number") return `${f.value.toLocaleString("en-IN")} units`;
  return String(f.value);
}

function ExtractionRow({ fieldKey, label, field }: { fieldKey: string; label: string; field?: CallFieldValidation }) {
  const filled = field !== undefined;
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line/60 py-2 last:border-b-0">
      <span className="text-[11.5px] text-ink-muted">{label}</span>
      {!filled ? (
        <span className="h-3.5 w-16 animate-pulse rounded-sm bg-surface-3" />
      ) : (
        <motion.span
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className={clsx(
            "numeric inline-flex items-center gap-1.5 text-[12.5px] font-medium",
            field.exceeds_guardrail ? "text-critical" : field.valid ? "text-ink" : "text-warning"
          )}
        >
          {fieldDisplay(fieldKey, field)}
          {field.exceeds_guardrail ? (
            <span className="rounded-sm bg-critical/12 px-1.5 py-px text-[9px] font-semibold text-critical uppercase">
              above guardrail
            </span>
          ) : field.valid ? (
            <CheckCircle2 size={13} className="text-success" />
          ) : (
            <AlertTriangle size={13} className="text-warning" />
          )}
        </motion.span>
      )}
    </div>
  );
}

// ---- the view --------------------------------------------------------------

export default function CallView({
  callId,
  initial,
  plan,
  onDone,
}: {
  callId: string;
  initial: CallSession | null;
  plan: Plan | null;
  onDone?: () => void;
}) {
  const [session, setSession] = useState<CallSession | null>(initial);
  const [turns, setTurns] = useState<WSEventPayloads["CALL_TRANSCRIPT"][]>([]);
  const [fields, setFields] = useState<Record<string, CallFieldValidation>>({});
  const [ended, setEnded] = useState<EndedPayload | null>(null);
  const [waitedOut, setWaitedOut] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);

  const transcriptEvents = useLiveEvents(useMemo(() => ["CALL_TRANSCRIPT" as const], []));
  const fieldEvents = useLiveEvents(useMemo(() => ["CALL_FIELD_EXTRACTED" as const], []));
  const endedEvents = useLiveEvents(useMemo(() => ["CALL_ENDED" as const], []));

  // Refresh recovery: render whatever already happened, then continue live.
  useEffect(() => {
    function hydrate(c: CallSession) {
      setSession(c);
      if (c.transcript.length > 0)
        setTurns((prev) => (prev.length > 0 ? prev : c.transcript.map((t) => ({ call_id: c.id, phase: "POST_CALL_REVEAL" as const, ...t }))));
      if (c.validation.fields) setFields((prev) => (Object.keys(prev).length > 0 ? prev : c.validation.fields!));
    }
    if (initial) hydrate(initial);
    else api.getCall(callId).then(hydrate).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callId]);

  useEffect(() => {
    const mine = transcriptEvents
      .map((e) => e.payload as WSEventPayloads["CALL_TRANSCRIPT"])
      .filter((p) => p.call_id === callId);
    if (mine.length === 0) return;
    setTurns((prev) => {
      const seen = new Set(prev.map((t) => t.seq));
      const additions = mine.filter((t) => !seen.has(t.seq));
      return additions.length ? [...prev, ...additions].sort((a, b) => a.seq - b.seq) : prev;
    });
  }, [transcriptEvents, callId]);

  useEffect(() => {
    for (const e of fieldEvents) {
      const p = e.payload as WSEventPayloads["CALL_FIELD_EXTRACTED"];
      if (p.call_id !== callId) continue;
      const { field, ...info } = p;
      setFields((prev) => (field in prev ? prev : { ...prev, [field]: info }));
    }
  }, [fieldEvents, callId]);

  useEffect(() => {
    const mine = endedEvents
      .map((e) => e.payload as EndedPayload)
      .find((p) => p.call_id === callId);
    if (mine && !ended) {
      setEnded(mine);
      onDone?.();
    }
  }, [endedEvents, callId, ended, onDone]);

  // Quiet waiting state if the webhook never lands.
  useEffect(() => {
    if (ended || turns.length > 0) return;
    const id = setTimeout(() => setWaitedOut(true), WEBHOOK_WAIT_TIMEOUT_MS);
    return () => clearTimeout(id);
  }, [ended, turns.length]);

  // Auto-scroll the transcript unless the user scrolled up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [turns.length]);

  const briefing = (session?.briefing_snapshot ?? {}) as Partial<CallBriefingSnapshot>;
  const guardrails = (session?.guardrails ?? {}) as Partial<CallGuardrails>;
  const revealing = turns.length > 0;
  const price = fields.unit_price;
  const priceAgreed = price && price.valid && typeof price.value === "number" ? (price.value as number) : null;

  const statusLabel = ended
    ? ended.outcome === "CONFIRMED" ? "Confirmed" : ended.outcome === "NEEDS_REVIEW" ? "Needs review" : "Ended"
    : revealing ? "Processing" : "Live";
  const statusTone = ended
    ? ended.outcome === "CONFIRMED" ? "bg-success/12 text-success" : "bg-warning/12 text-warning"
    : revealing ? "bg-info/12 text-info" : "bg-accent/12 text-accent";

  const splitRecipients: SplitRecipient[] = useMemo(() => {
    if (!plan) return [];
    const byVendor = new Map<string, SplitRecipient>();
    for (const change of plan.changes) {
      for (const row of change.proposed) {
        const key = row.vendor_id || row.vendor_name;
        const amount = row.qty * row.unit_price_paise;
        const existing = byVendor.get(key);
        const isCallVendor = session?.vendor_id === row.vendor_id && priceAgreed !== null;
        const rowAmount = isCallVendor ? row.qty * priceAgreed : amount;
        if (existing) existing.amount_paise += rowAmount;
        else
          byVendor.set(key, {
            id: key,
            name: row.vendor_name,
            amount_paise: rowAmount,
            detail: `${row.qty.toLocaleString("en-IN")} × ${isCallVendor && priceAgreed !== null ? formatPaiseFull(priceAgreed) : row.unit_price_display}`,
            internal: change.kind === "PULL_FORWARD_STOCK",
          });
      }
    }
    return [...byVendor.values()];
  }, [plan, session?.vendor_id, priceAgreed]);
  const splitTotal = splitRecipients.reduce((sum, r) => sum + r.amount_paise, 0);

  return (
    <div className="flex h-full flex-col">
      <div className="flex min-h-0 flex-1">
        {/* LEFT — call status */}
        <div className="flex w-[220px] shrink-0 flex-col gap-4 border-r border-line p-4">
          <div>
            <p className="eyebrow mb-1">Voice negotiation</p>
            <p className="text-[14px] font-semibold text-ink">{briefing.vendor_name ?? "Vendor"}</p>
            <p className="numeric mt-0.5 text-[11.5px] text-ink-muted">{session?.phone ?? "•••"}</p>
            {session?.language && (
              <span className="mt-1.5 inline-block rounded-sm bg-surface-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-muted uppercase">
                {session.language}
              </span>
            )}
          </div>
          <Waveform active={!ended} />
          {session && <CallTimer startedAt={session.started_at} stopped={!!ended} />}
          <span className={clsx("inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold", statusTone)}>
            <PhoneCall size={11} />
            {statusLabel}
          </span>
          {!ended && !revealing && (
            <p className="text-[11px] leading-relaxed text-ink-faint">
              Listening on the vendor&apos;s line — the outcome arrives when the call ends.
            </p>
          )}
          {!ended && !revealing && session?.source === "LIVE_BOLNA" && (
            <p className="rounded-md border border-dashed border-line px-2 py-1.5 text-[10.5px] text-ink-muted">
              Operator: now dial from the agent dashboard.
            </p>
          )}
          {waitedOut && !revealing && !ended && (
            <div className="space-y-2">
              <p className="text-[11px] text-ink-muted">Still waiting for the call outcome.</p>
              {DEMO_CONTROLS && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={replaying}
                  onClick={() => {
                    setReplaying(true);
                    api.replayLastCall(callId).catch(() => undefined).finally(() => setReplaying(false));
                  }}
                >
                  {replaying ? "Replaying…" : "Replay last call"}
                </Button>
              )}
            </div>
          )}
        </div>

        {/* CENTRE — briefing, then transcript beside it */}
        <div className="flex min-w-0 flex-1">
          <motion.div
            layout
            transition={{ duration: 0.5, ease: "easeOut" }}
            className={clsx("shrink-0 overflow-y-auto p-5", revealing ? "w-[300px] border-r border-line" : "w-full")}
          >
            <p className="eyebrow mb-3">What Sanjeevani told the agent</p>
            {briefing.briefing ? (
              <blockquote className={clsx("leading-relaxed text-ink", revealing ? "text-[14px]" : "text-[19px]")}>
                “{briefing.briefing}”
              </blockquote>
            ) : (
              <Spinner size={16} label="Loading briefing…" />
            )}
            <div className={clsx("mt-5 grid gap-3", revealing ? "grid-cols-1" : "grid-cols-2")}>
              <div
                className={clsx(
                  "rounded-lg border p-3",
                  price?.exceeds_guardrail ? "animate-pulse border-critical bg-critical/8" : "border-line bg-surface-2/50"
                )}
              >
                <p className="eyebrow">Max price</p>
                <p className={clsx("numeric mt-1 font-semibold", revealing ? "text-xl" : "text-3xl", price?.exceeds_guardrail ? "text-critical" : "text-ink")}>
                  {guardrails.max_unit_price_display ?? briefing.max_unit_price ?? "—"}
                </p>
                <p className="mt-0.5 text-[10px] text-ink-faint">hard guardrail</p>
              </div>
              <div className="rounded-lg border border-line bg-surface-2/50 p-3">
                <p className="eyebrow">Max lead time</p>
                <p className={clsx("numeric mt-1 font-semibold text-ink", revealing ? "text-xl" : "text-3xl")}>
                  {guardrails.max_lead_time_days ?? briefing.max_lead_time_days ?? "—"}d
                </p>
                <p className="mt-0.5 text-[10px] text-ink-faint">hard guardrail</p>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-[11.5px] text-ink-muted">
              <span>Target: <span className="numeric text-ink">{briefing.target_unit_price ?? "—"}</span></span>
              <span>Last agreed: <span className="numeric text-ink">{briefing.last_agreed_price ?? "—"}</span></span>
              <span>Reliability: <span className="text-ink">{briefing.reliability ?? "—"}</span></span>
              <span>Item: <span className="text-ink">{briefing.item_name ?? "—"}</span></span>
            </div>
          </motion.div>

          {revealing && (
            <div className="relative flex min-w-0 flex-1 flex-col">
              <div className="flex items-baseline justify-between border-b border-line px-4 py-2.5">
                <p className="eyebrow">Call transcript</p>
                <span className="text-[10px] text-ink-faint">captured after call</span>
              </div>
              <div
                ref={scrollRef}
                onScroll={(e) => {
                  const el = e.currentTarget;
                  pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
                }}
                className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4"
              >
                {turns.map((t) => {
                  const isAgent = t.speaker === "ASSISTANT" || t.speaker === "AGENT";
                  return (
                    <motion.div
                      key={t.seq}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      className={clsx("max-w-[85%] rounded-lg px-3 py-2 text-[12.5px] leading-relaxed", isAgent ? "bg-accent/10 text-ink" : "ml-auto bg-surface-2 text-ink")}
                    >
                      <p className="mb-0.5 text-[9.5px] font-semibold tracking-wide text-ink-faint uppercase">
                        {isAgent ? "Dhrithi (agent)" : "Vendor"}
                      </p>
                      <TypeText text={t.text} />
                    </motion.div>
                  );
                })}
              </div>

              {/* Outcome card rises over the transcript */}
              <AnimatePresence>
                {ended && (
                  <motion.div
                    initial={{ y: 60, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.5, ease: "easeOut" }}
                    className="absolute inset-x-3 bottom-3 rounded-lg border border-line bg-surface p-4 shadow-lg"
                  >
                    <div className="mb-2.5 flex items-center justify-between gap-2">
                      <p className="text-[13.5px] font-semibold text-ink">
                        {ended.outcome === "CONFIRMED" ? "Terms confirmed" : ended.outcome === "NEEDS_REVIEW" ? "Outcome needs review" : "Call ended — incomplete data"}
                      </p>
                      <span
                        className={clsx(
                          "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
                          ended.guardian.passed ? "bg-success/12 text-success" : "bg-warning/12 text-warning"
                        )}
                      >
                        {ended.guardian.passed ? <ShieldCheck size={11} /> : <ShieldAlert size={11} />}
                        {ended.guardian.label}
                      </span>
                    </div>
                    <div className="numeric flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-muted">
                      {priceAgreed !== null && <span>Agreed <span className="font-semibold text-ink">{formatPaiseFull(priceAgreed)}/unit</span></span>}
                      {fields.delivery_date?.valid && <span>Delivery <span className="text-ink">{String(fields.delivery_date.value)}</span></span>}
                      {ended.exposure_after && (
                        <span>
                          Exposure now <span className="font-semibold text-success">{ended.exposure_after.total_display}</span>
                        </span>
                      )}
                      {ended.new_stage && <span>Stage → <span className="text-ink">{ended.new_stage}</span></span>}
                    </div>
                    {splitRecipients.length > 0 && (
                      <div className="mt-3">
                        <PaymentSplitFlow
                          compact
                          totalPaise={splitTotal}
                          recipients={splitRecipients}
                          title="How the payment splits"
                          note="One settlement, routed per the approved plan — the called vendor's line reflects the price agreed on this call."
                        />
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>

        {/* RIGHT — extraction panel */}
        <div className="w-[250px] shrink-0 border-l border-line p-4">
          <p className="eyebrow mb-2">Extracted terms</p>
          {FIELD_ROWS.map((row) => (
            <ExtractionRow key={row.key} fieldKey={row.key} label={row.label} field={fields[row.key]} />
          ))}
          <p className="mt-3 text-[10px] leading-relaxed text-ink-faint">
            Fields fill in when the post-call webhook lands. Validation is deterministic — no model touches these numbers.
          </p>
        </div>
      </div>

      {/* BOTTOM — reasoning line */}
      <div className="numeric border-t border-line px-4 py-2 text-[11.5px] text-ink-muted">
        {guardrails.max_unit_price_display ? (
          <>
            guardrail: max {guardrails.max_unit_price_display}/unit
            {priceAgreed !== null && (
              <>
                {" · agreed "}
                <span className={price?.exceeds_guardrail ? "font-semibold text-critical" : "font-semibold text-ink"}>
                  {formatPaiseFull(priceAgreed)}
                </span>
                {price?.exceeds_guardrail ? " · above limit — needs review" : " · within limit"}
              </>
            )}
          </>
        ) : (
          "guardrails loading…"
        )}
      </div>
    </div>
  );
}
