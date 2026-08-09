"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  FileSpreadsheet,
  KeyRound,
  Loader2,
  Mic,
  MicOff,
  ReceiptText,
  Send,
  Sparkles,
  Square,
  Wallet,
} from "lucide-react";
import clsx from "clsx";
import Link from "next/link";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
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
    /* min-w-0 lets the stepper actually shrink inside the deck. Without it the
       ol's own overflow-x-auto never engages — it isn't the box that overflows,
       its parent is, and the excess lands under the fixed sidebar instead. */
    <div className="pointer-events-auto flex min-w-0 max-w-full flex-col items-center">
      <div className="mb-3 max-w-full text-center">
        {/* The one text node here with no natural bound: an 80-char vendor name
            measured 828px on one line, widening the whole block past the ol's
            max-width and stealing 25px of vertical budget when it wrapped. */}
        <h2 className="font-display max-w-full truncate text-[20px] leading-tight font-bold text-ink">
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

      {/* Bounded by the deck's own width, not the viewport's: 92vw measured a
          box 232px wider than the space actually available beside the sidebar,
          which put the first phase behind it and the last past the frame edge. */}
      <ol className="glass flex max-w-full items-start gap-1 overflow-x-auto px-6 py-4 lg:max-w-[860px]">
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

/* A readout inside the metrics panel, not a card of its own. The three of them
   are one group — passive, glanced at, never touched — so they share a single
   glass surface with hairline dividers. As four equal tiles they claimed the
   same weight as the assistant, which is an interactive session with focus, an
   input, and unbounded content; the grid asserted an equality the content
   contradicts, and that false peerage is what forced both the wasted space and
   the overflow below 1280px. */
function MetricBlock({
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
    <div className="flex flex-col p-5">
      <header
        className={clsx(
          "mb-3 flex items-center gap-2",
          tone === "alert" ? "text-critical" : tone === "accent" ? "text-accent" : "text-ink-muted"
        )}
      >
        <Icon size={16} />
        <h3 className="eyebrow !text-current">{label}</h3>
      </header>
      {children}
    </div>
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

/* ---------------- Ops assistant ---------------- */

/* A real ElevenLabs agent, typed or spoken. The API key never leaves the
   server: /api/voice/signed-url mints a 15-minute WebSocket URL and that URL
   is the only credential this component ever holds. Signed URLs pin the
   transport to WebSocket — WebRTC would need a conversation token instead. */

type SignedUrlPayload =
  | { configured: false; reason: string }
  | { configured: true; signedUrl: string | null; reason?: string };

type AssistantState =
  | { kind: "loading" }
  | { kind: "ready" }
  | { kind: "unconfigured"; reason: string }
  | { kind: "unreachable"; reason: string };

type Turn = { id: string; role: "you" | "agent"; text: string };

// Signed URLs live 15 minutes. Reuse well inside that so a session can never
// open against one that expires mid-handshake.
const SIGNED_URL_REUSE_MS = 10 * 60 * 1000;

/* Returns what the route said, and nothing else — the caller decides what to
   do with it. Every failure path resolves rather than throws: not being
   configured yet is a state this panel renders, not an exception. */
async function requestSignedUrl(): Promise<{ state: AssistantState; url: string | null }> {
  try {
    const response = await fetch("/api/voice/signed-url", { cache: "no-store" });
    const payload = (await response.json()) as SignedUrlPayload;

    if (!payload.configured) return { state: { kind: "unconfigured", reason: payload.reason }, url: null };
    if (!payload.signedUrl) {
      return { state: { kind: "unreachable", reason: payload.reason ?? "No signed URL was issued." }, url: null };
    }
    return { state: { kind: "ready" }, url: payload.signedUrl };
  } catch {
    return { state: { kind: "unreachable", reason: "The signed-URL route did not respond." }, url: null };
  }
}

function SetupNotice({ reason }: { reason: string }) {
  return (
    <div className="space-y-2">
      <p className="flex items-center gap-1.5 text-[12px] font-semibold text-ink">
        <KeyRound size={13} className="shrink-0 text-warning" />
        Assistant not configured
      </p>
      <p className="text-[11px] leading-snug text-ink-muted">{reason}</p>
      <ul className="space-y-1.5">
        <li>
          <code className="numeric block text-[10.5px] font-semibold text-accent">ELEVENLABS_API_KEY</code>
          <span className="text-[10.5px] text-ink-faint">ElevenLabs → Settings → API keys</span>
        </li>
        <li>
          <code className="numeric block text-[10.5px] font-semibold text-accent">ELEVENLABS_AGENT_ID</code>
          <span className="text-[10.5px] text-ink-faint">ElevenLabs → Agents → your agent</span>
        </li>
      </ul>
      <a
        href="https://elevenlabs.io"
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 rounded-sm text-[11px] font-medium text-accent outline-offset-2 hover:underline"
      >
        Open ElevenLabs
        <ExternalLink size={11} />
      </a>
    </div>
  );
}

/* The one place in this deck that animates without being a status change —
   and it is one: the agent holds the floor until these stop. Built from the
   shared `animate-blink` keyframe, so the global prefers-reduced-motion rule
   in globals.css flattens it along with everything else. */
function SpeakingDots() {
  return (
    <span className="flex items-center gap-1 px-2.5 py-1.5" aria-label="Assistant is speaking">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="animate-blink size-1.5 rounded-full bg-accent"
          style={{ animationDelay: `${i * 180}ms` }}
        />
      ))}
    </span>
  );
}

function AssistantConversation() {
  const [state, setState] = useState<AssistantState>({ kind: "loading" });
  const [turns, setTurns] = useState<Turn[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // Whether the live session carries audio. A text-only session reports the
  // same "listening" mode as a voice one, so the SDK cannot tell us this.
  const [voice, setVoice] = useState(false);

  const signedUrlRef = useRef<{ url: string; at: number } | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  // Text typed before the socket is open; flushed once it is.
  const outboxRef = useRef<string[]>([]);
  // Set when a mode switch has to wait for the current session to close.
  const pendingStartRef = useRef<{ textOnly: boolean } | null>(null);
  const lastTypedRef = useRef<string | null>(null);

  const conversation = useConversation({
    onConnect: () => setNotice(null),
    onError: (message) => setNotice(message),
    onMessage: ({ message, role }) => {
      // A typed turn comes back as a user transcript. It is already on screen,
      // so the echo is dropped rather than rendered twice.
      if (role === "user" && lastTypedRef.current === message.trim()) {
        lastTypedRef.current = null;
        return;
      }
      setTurns((current) => [
        ...current,
        { id: crypto.randomUUID(), role: role === "agent" ? "agent" : "you", text: message },
      ]);
    },
  });

  const { status, isSpeaking, isMuted, setMuted, startSession, endSession, sendUserMessage } =
    conversation;
  const live = status === "connected" || status === "connecting";

  const applySignedUrl = useCallback((result: { state: AssistantState; url: string | null }) => {
    if (result.url) signedUrlRef.current = { url: result.url, at: Date.now() };
    setState(result.state);
    return result.url;
  }, []);

  const ensureSignedUrl = useCallback(async () => {
    const cached = signedUrlRef.current;
    if (cached && Date.now() - cached.at < SIGNED_URL_REUSE_MS) return cached.url;
    return applySignedUrl(await requestSignedUrl());
  }, [applySignedUrl]);

  // Asked for on mount, before anyone touches the panel: whether credentials
  // exist is only knowable server-side, and the panel has to be able to say
  // plainly that they are missing rather than fail on first use.
  useEffect(() => {
    let active = true;
    void requestSignedUrl().then((result) => {
      if (active) applySignedUrl(result);
    });
    return () => {
      active = false;
    };
  }, [applySignedUrl]);

  const beginSession = useCallback(
    async (textOnly: boolean) => {
      const url = await ensureSignedUrl();
      if (!url) return;

      // The SDK provider refuses a second startSession while one is open, so a
      // switch between typed and spoken has to wait for the close to land —
      // picked up by the effect below once status settles.
      if (live) {
        pendingStartRef.current = { textOnly };
        endSession();
        return;
      }

      setVoice(!textOnly);
      startSession({ signedUrl: url, connectionType: "websocket", textOnly });
    },
    [ensureSignedUrl, live, startSession, endSession]
  );

  useEffect(() => {
    if (status !== "disconnected") return;
    const pending = pendingStartRef.current;
    const url = signedUrlRef.current?.url;
    if (!pending || !url) return;

    pendingStartRef.current = null;
    setVoice(!pending.textOnly);
    startSession({ signedUrl: url, connectionType: "websocket", textOnly: pending.textOnly });
  }, [status, startSession]);

  useEffect(() => {
    if (status !== "connected" || outboxRef.current.length === 0) return;
    const queued = outboxRef.current;
    outboxRef.current = [];
    for (const text of queued) sendUserMessage(text);
  }, [status, sendUserMessage]);

  useEffect(() => {
    const element = transcriptRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns, isSpeaking, state.kind]);

  // The provider tears the session down on unmount too; this makes the panel's
  // own contract explicit rather than inherited.
  useEffect(() => () => endSession(), [endSession]);

  function handleSend() {
    const text = draft.trim();
    if (!text || state.kind === "unconfigured") return;

    setTurns((current) => [...current, { id: crypto.randomUUID(), role: "you", text }]);
    lastTypedRef.current = text;
    setDraft("");

    if (status === "connected") {
      sendUserMessage(text);
      return;
    }
    outboxRef.current.push(text);
    // Already connecting: the flush effect will send it the moment it opens.
    if (status !== "connecting") void beginSession(true);
  }

  async function handleMic() {
    setNotice(null);
    if (live) {
      endSession();
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setNotice("Voice needs a secure page — open the console over https or on localhost.");
      return;
    }

    // The permission prompt has to hang off this click, so it is requested
    // before anything is awaited. The SDK opens its own capture stream, so
    // this one is released immediately — it was only ever asking.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      for (const track of stream.getTracks()) track.stop();
    } catch {
      setNotice("Microphone blocked. Allow it in the address bar, then press the mic again.");
      return;
    }

    await beginSession(false);
  }

  const connection =
    status === "connected"
      ? voice
        ? isSpeaking
          ? { label: "Speaking", dot: "bg-accent animate-blink" }
          : { label: "Listening", dot: "bg-success" }
        : { label: "Connected", dot: "bg-success" }
      : status === "connecting"
        ? { label: "Connecting", dot: "bg-warning animate-blink" }
        : status === "error"
          ? { label: "Error", dot: "bg-critical" }
          : { label: "Idle", dot: "bg-line-strong" };

  return (
    <>
      <header className="mb-3 flex items-center gap-2 text-accent">
        <Sparkles size={16} />
        <h3 className="eyebrow !text-current">Ops assistant</h3>

        <div className="ml-auto flex items-center gap-2">
          {voice && status === "connected" && (
            <button
              onClick={() => setMuted(!isMuted)}
              aria-pressed={isMuted}
              aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
              className={clsx(
                "flex size-6 items-center justify-center rounded-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                isMuted ? "bg-critical-dim text-critical" : "text-ink-faint hover:text-accent"
              )}
            >
              {isMuted ? <MicOff size={12} /> : <Mic size={12} />}
            </button>
          )}
          {state.kind !== "unconfigured" && state.kind !== "loading" && (
            <span className="flex items-center gap-1.5 text-[10.5px] font-medium text-ink-muted">
              <span className={clsx("size-1.5 rounded-full", connection.dot)} />
              {connection.label}
            </span>
          )}
        </div>
      </header>

      <div
        ref={transcriptRef}
        aria-live="polite"
        className="mb-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto text-[12px] leading-relaxed"
      >
        {state.kind === "loading" && (
          <>
            <span className="skeleton block h-3 w-40" />
            <span className="skeleton block h-3 w-28" />
          </>
        )}

        {state.kind === "unconfigured" && <SetupNotice reason={state.reason} />}

        {(state.kind === "ready" || state.kind === "unreachable") && (
          <>
            {turns.length === 0 && (
              <p className="mr-2 rounded-md bg-surface/70 px-2.5 py-1.5 text-ink-muted">
                Ask about a vendor, disruption, or shipment — type it, or press the mic to talk.
              </p>
            )}
            {turns.map((turn) => (
              <p
                key={turn.id}
                className={clsx(
                  "rounded-md px-2.5 py-1.5",
                  turn.role === "you" ? "ml-6 bg-accent text-accent-ink" : "mr-2 bg-surface/70 text-ink-muted"
                )}
              >
                {turn.text}
              </p>
            ))}
            {isSpeaking && <SpeakingDots />}
            {(notice || state.kind === "unreachable") && (
              <p className="flex items-start gap-1.5 text-[11px] leading-snug text-critical">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                {notice ?? (state.kind === "unreachable" ? state.reason : null)}
              </p>
            )}
          </>
        )}
      </div>

      {state.kind !== "unconfigured" && (
        <div className="flex items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 transition-colors duration-150 focus-within:border-accent">
          <button
            onClick={handleMic}
            disabled={state.kind === "loading"}
            aria-label={live ? "End voice session" : "Start voice session"}
            className={clsx(
              "flex size-7 shrink-0 items-center justify-center rounded-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40",
              live ? "bg-critical-dim text-critical" : "text-ink-faint hover:bg-surface-2 hover:text-accent"
            )}
          >
            {status === "connecting" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : live ? (
              <Square size={11} fill="currentColor" />
            ) : (
              <Mic size={14} />
            )}
          </button>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && handleSend()}
            className="min-w-0 flex-1 bg-transparent text-[12px] text-ink outline-none placeholder:text-ink-faint"
            placeholder="Ask about the network…"
            aria-label="Ask the operations assistant"
          />
          <button
            onClick={handleSend}
            disabled={state.kind === "loading"}
            aria-label="Send"
            className="flex size-7 shrink-0 items-center justify-center rounded-sm text-accent transition-colors duration-150 hover:bg-accent-dim focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40"
          >
            <Send size={14} />
          </button>
        </div>
      )}

      {/* Spreadsheets belong in the ingest flow, which shows live parse
          progress per file — this panel only points at it. */}
      <Link
        href="/onboarding"
        className="mt-2 inline-flex self-start items-center gap-1.5 rounded-sm text-[10.5px] text-ink-faint outline-offset-2 transition-colors duration-150 hover:text-accent"
      >
        <FileSpreadsheet size={11} />
        Import Excel or CSV in Data sources
      </Link>
    </>
  );
}

function AssistantTile() {
  return (
    /* Definite height, not min-height: the transcript is `flex-1
       overflow-y-auto`, and that only scrolls when its parent is bounded —
       with min-h the tile grew with the conversation and dragged the row out
       of the map frame. Scaled to the viewport rather than pinned at one
       value, because a fixed 232px left the transcript 89px tall (about three
       lines) on every screen regardless of how much room there was. */
    <section className="glass pointer-events-auto flex h-[clamp(212px,26vh,300px)] flex-col p-5">
      {/* useConversation reads this context and throws without it. Mounted here
          rather than app-wide so a session's lifetime is exactly the panel's. */}
      <ConversationProvider>
        <AssistantConversation />
      </ConversationProvider>
    </section>
  );
}

/* ---------------- Deck ---------------- */

/* The demo control bar is a fixed, env-gated overlay pinned to the bottom-left
   of the viewport, so the deck reserves room for it — and only then, since the
   bar is absent in normal operation and a permanent gap would be dead space.
   It now collapses to a single pill by default, so this only has to clear that
   pill rather than the three wrapped rows the expanded bar occupies. */
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
        /* padding-bottom is never set by a shorthand here. `sm:p-6` lives in a
           media query, so Tailwind emits it after the un-prefixed `pb-[68px]`
           and silently wins at >=640px — the demo bar's reserved gap vanished
           and its pill landed back on the metrics panel. Separate axes, one
           owner each, no collision. */
        "pointer-events-none absolute inset-0 z-20 flex flex-col justify-between gap-4 px-4 pt-4 sm:gap-6 sm:px-6 sm:pt-6",
        DEMO_CONTROLS ? "pb-[76px]" : "pb-4 sm:pb-6"
      )}
    >
      <div className="flex justify-center pt-1">
        <FocusStepper disruption={focus} />
      </div>

      {/* Two members, not four: the readouts as one panel, the assistant as its
          own. Four equal tiles stacked into a 2x2 between 640-1279px wide, and
          that 480px block needed 797px of viewport height — at 1024x768 it ran
          past the frame with no scroll recovery, leaving the assistant's input
          rendered but unhittable. Aligned to the bottom so the shorter panel
          hangs off the same baseline as the taller one. */}
      <div className="mx-auto grid w-full max-w-[1240px] items-end gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section className="glass pointer-events-auto grid divide-y divide-line/60 sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <MetricBlock label="Global exposure" icon={Wallet}>
            <div className="flex flex-col gap-2.5">
              <MetricRow
                divider
                tone="critical"
                value={summary?.exposure_at_risk_display ?? "—"}
                label="At risk"
              />
              <MetricRow tone="accent" value={summary?.exposure_mitigated_display ?? "—"} label="Mitigated" />
            </div>
          </MetricBlock>

          <MetricBlock label="Active disruptions" icon={AlertTriangle} tone="alert">
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
          </MetricBlock>

          <MetricBlock label="Vendor dues" icon={ReceiptText}>
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
          </MetricBlock>
        </section>

        <AssistantTile />
      </div>
    </div>
  );
}
