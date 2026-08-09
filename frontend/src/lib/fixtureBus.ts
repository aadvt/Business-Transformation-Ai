// Cross-tab event bus for NEXT_PUBLIC_USE_FIXTURES=true mode. Real mode gets
// cross-window causality for free (both /command and /phone connect to the
// same backend WebSocket); fixture mode has no backend to broadcast from, so
// this stands in for it via BroadcastChannel — same origin, any number of
// tabs, no server. LiveFeedProvider (see live.tsx) subscribes to this
// instead of opening a real socket when fixtures are on; anything that would
// otherwise wait on a real WS event (D4's phone -> command approval
// handoff, chiefly) publishes here instead.

import type { WSEvent, WSEventType } from "./types";

const CHANNEL_NAME = "sanjeevani-fixture-bus";

let channel: BroadcastChannel | null = null;
let seq = 0;

function getChannel(): BroadcastChannel | null {
  if (typeof window === "undefined") return null;
  if (!channel) channel = new BroadcastChannel(CHANNEL_NAME);
  return channel;
}

export function publishFixtureEvent<T extends WSEventType>(
  type: T,
  payload: Record<string, unknown>,
  disruptionId: string | null = null
): WSEvent {
  const event = {
    event_id: `fixture-${Date.now()}-${seq++}`,
    type,
    at: new Date().toISOString(),
    disruption_id: disruptionId,
    payload,
  } as WSEvent;

  // Same-tab listeners don't receive their own postMessage — dispatch a
  // local CustomEvent too so the tab that publishes also reacts, matching
  // how a real socket would echo the effect of your own action back to you.
  getChannel()?.postMessage(event);
  window.dispatchEvent(new CustomEvent<WSEvent>("fixture-bus-local", { detail: event }));
  return event;
}

export function subscribeFixtureEvents(handler: (event: WSEvent) => void): () => void {
  const ch = getChannel();
  const onMessage = (e: MessageEvent) => handler(e.data as WSEvent);
  const onLocal = (e: Event) => handler((e as CustomEvent<WSEvent>).detail);

  ch?.addEventListener("message", onMessage);
  window.addEventListener("fixture-bus-local", onLocal);

  return () => {
    ch?.removeEventListener("message", onMessage);
    window.removeEventListener("fixture-bus-local", onLocal);
  };
}
