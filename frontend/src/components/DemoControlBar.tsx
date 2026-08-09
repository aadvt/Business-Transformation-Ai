"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronUp, RotateCcw, RotateCw, Radio, Sheet, SlidersHorizontal, X } from "lucide-react";
import { api } from "@/lib/api";
import { useLiveFeed } from "@/lib/live";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const ENABLED = process.env.NEXT_PUBLIC_DEMO_CONTROLS === "true";
const MODES = ["ingest", "briefing", "impact", "candidates", "plan", "call", "outcome"];

export default function DemoControlBar() {
  const router = useRouter();
  const { connectionState, allEvents } = useLiveFeed();
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Collapsed by default. Expanded, this bar is 620x70px pinned over the
  // canvas's bottom-left — exactly where the approval card with the "Call
  // vendor" button lives — so it used to bury the operator's next action.
  const [open, setOpen] = useState(false);
  const [replay, setReplay] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sheetState, setSheetState] = useState<"idle" | "pending" | "synced" | "unavailable">("idle");

  const lastCallId = allEvents.find((event) => event.type === "CALL_ENDED" || event.type === "CALL_STARTED")?.payload;
  const callId = lastCallId && "call_id" in lastCallId ? lastCallId.call_id : undefined;
  const webhookReceived = allEvents.some((event) => ["CALL_TRANSCRIPT", "CALL_FIELD_EXTRACTED", "CALL_ENDED"].includes(event.type));
  const webhookLabel = webhookReceived ? "Webhook received" : callId ? "Waiting for webhook" : "Webhook idle";
  const webhookDot = webhookReceived ? "bg-success" : callId ? "bg-warning" : "bg-ink-faint";

  useEffect(() => {
    if (!ENABLED) return;
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      const index = Number(event.key) - 1;
      if (index >= 0 && index < MODES.length) router.push(`/command?mode=${MODES[index]}`);
      if (event.key.toLowerCase() === "r") handleReplay();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (!ENABLED) return null;

  function jump(mode: string) {
    const disruptionId = typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("d");
    router.push(`/command?${disruptionId ? `d=${disruptionId}&` : ""}mode=${mode}`);
  }

  async function reset() {
    await api.resetDemo();
    setConfirmOpen(false);
    router.push("/command");
  }

  async function syncSheet() {
    setSyncing(true);
    setSheetState("pending");
    try {
      const disruptionId = typeof window === "undefined" ? undefined : new URLSearchParams(window.location.search).get("d") ?? undefined;
      const result = await api.syncAgentSheet(disruptionId);
      setSheetState(result.status === "SYNCED" ? "synced" : "unavailable");
    } catch {
      setSheetState("unavailable");
    } finally {
      setSyncing(false);
    }
  }

  async function handleReplay() {
    if (!callId) return;
    await api.replayLastCall(callId);
  }

  return (
    <>
      {open ? (
        <div className="fixed bottom-3 left-[228px] z-40 w-[min(620px,calc(100vw-250px))] rounded-lg border border-line bg-surface p-2 shadow-lg">
          <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
            <Button size="sm" variant="destructive" onClick={() => setConfirmOpen(true)} icon={<RotateCcw size={13} />}>Reset demo</Button>
            <span className="mx-1 h-5 w-px bg-line" />
            {MODES.map((mode, index) => <Button key={mode} size="sm" variant="ghost" onClick={() => jump(mode)}>{index + 1} {mode[0].toUpperCase() + mode.slice(1)}</Button>)}
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Hide demo controls"
              className="ml-auto rounded p-1 text-ink-faint hover:bg-surface-2 hover:text-ink"
            >
              <X size={14} />
            </button>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-ink-muted">
            <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-1 hover:bg-surface-2" onClick={() => setReplay((value) => !value)}><Radio size={12} /> {replay ? "Replay" : "Live"}</button>
            <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-1 hover:bg-surface-2" onClick={syncSheet} disabled={syncing}><Sheet size={12} /> {sheetState === "pending" ? "Syncing…" : "Sync vendor sheet"}</button>
            <button type="button" className="inline-flex items-center gap-1 rounded px-1.5 py-1 hover:bg-surface-2" onClick={handleReplay} disabled={!callId}><RotateCw size={12} /> Replay last call <kbd className="ml-1 rounded bg-surface-2 px-1">R</kbd></button>
            <span className="inline-flex items-center gap-1"><span className={`h-1.5 w-1.5 rounded-full ${connectionState === "open" ? "bg-success" : "bg-warning animate-blink"}`} />{connectionState === "open" ? "WS live" : "reconnecting"}</span>
            <span className="inline-flex items-center gap-1"><span className={`h-1.5 w-1.5 rounded-full ${webhookDot}`} />{webhookLabel}</span>
          </div>
        </div>
      ) : (
        // Collapsed: just the two status dots the operator glances at, plus a
        // handle. Small enough to clear the canvas entirely.
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="fixed bottom-3 left-[228px] z-40 inline-flex items-center gap-2 rounded-lg border border-line bg-surface/90 px-2.5 py-1.5 text-[11px] text-ink-muted shadow-sm backdrop-blur transition-colors hover:bg-surface hover:text-ink"
        >
          <SlidersHorizontal size={12} />
          Demo
          <span className="h-3 w-px bg-line" />
          <span className={`h-1.5 w-1.5 rounded-full ${connectionState === "open" ? "bg-success" : "bg-warning animate-blink"}`} />
          <span className={`h-1.5 w-1.5 rounded-full ${webhookDot}`} />
          <ChevronUp size={12} />
        </button>
      )}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Reset the demo?</DialogTitle><DialogDescription>This clears the current demo state. Use it only before restarting a run.</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="secondary" onClick={() => setConfirmOpen(false)}>Cancel</Button><Button variant="destructive" onClick={reset}>Reset demo</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
