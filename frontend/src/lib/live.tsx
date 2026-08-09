"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { wsUrl } from "./api";
import { subscribeFixtureEvents } from "./fixtureBus";
import type { WSEvent, WSEventType } from "./types";

const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "true";

export type ConnectionState = "connecting" | "open" | "closed";

interface LiveFeedContextValue {
  connectionState: ConnectionState;
  events: WSEvent[];
  // Unfiltered event log (still excludes HEARTBEAT), kept separately from
  // `events` above and capped higher so useLiveEvents(types) below has
  // enough history to fill its own 100-event cap per type. `events` stays
  // untouched — it's the existing invalidation-only feed other components
  // already read.
  allEvents: WSEvent[];
}

const LiveFeedContext = createContext<LiveFeedContextValue>({ connectionState: "connecting", events: [], allEvents: [] });

// Which query key prefixes to invalidate when each WS event type arrives.
// Prefix arrays match React Query's default (non-exact) invalidation, so
// e.g. ["disruptions"] also invalidates ["disruptions", "AWAITING_APPROVAL"].
const EVENT_INVALIDATIONS: Partial<Record<WSEventType, string[][]>> = {
  AGENT_STATUS_CHANGED: [["agentsStatus"]],
  DISRUPTION_CREATED: [["disruptions"], ["dashboardSummary"]],
  STAGE_CHANGED: [["disruptions"], ["disruption"], ["dashboardSummary"], ["phoneMessages"]],
  EXPOSURE_COMPUTED: [["disruption"], ["dashboardSummary"]],
  CANDIDATES_FOUND: [["disruption"]],
  APPROVAL_REQUESTED: [["disruptions"], ["disruption"], ["dashboardSummary"], ["phoneMessages"]],
  APPROVAL_DECIDED: [["disruptions"], ["disruption"], ["dashboardSummary"], ["phoneMessages"]],
  NEGOTIATION_UPDATE: [["disruption"], ["disruptions"], ["phoneMessages"]],
  SETTLEMENT_STAGED: [["settlementBatches"], ["dashboardSummary"]],
  IMPACT_COMPUTED: [["impact"], ["disruption"]],
  PLAN_PROPOSED: [["plan"], ["disruption"]],
  CALL_STARTED: [["call"]],
  CALL_TRANSCRIPT: [["call"]],
  CALL_FIELD_EXTRACTED: [["call"]],
  CALL_ENDED: [["call"]],
  INGEST_PROGRESS: [["ingest"]],
  BRIEFING_READY: [["briefing"]],
  AGENT_SHEET_SYNCED: [["agentSheet"]],
};

const MAX_EVENTS = 50;
const MAX_ALL_EVENTS = 300;

export function LiveFeedProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState<WSEvent[]>([]);
  const [allEvents, setAllEvents] = useState<WSEvent[]>([]);
  const retryCountRef = useRef(0);

  useEffect(() => {
    function handleEvent(parsed: WSEvent) {
      if (parsed.type !== "HEARTBEAT") {
        setEvents((prev) => [parsed, ...prev].slice(0, MAX_EVENTS));
        setAllEvents((prev) => [parsed, ...prev].slice(0, MAX_ALL_EVENTS));
      }
      for (const key of EVENT_INVALIDATIONS[parsed.type] ?? []) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    }

    // Fixture mode: no backend to connect to. Cross-tab causality (D4's
    // /phone -> /command approval handoff) comes from fixtureBus instead —
    // see its header comment for why.
    if (USE_FIXTURES) {
      setConnectionState("open");
      return subscribeFixtureEvents(handleEvent);
    }

    let socket: WebSocket | null = null;
    let cancelled = false;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      if (cancelled) return;
      setConnectionState("connecting");
      socket = new WebSocket(wsUrl());

      socket.onopen = () => {
        retryCountRef.current = 0;
        setConnectionState("open");
      };

      socket.onmessage = (event) => {
        let parsed: WSEvent;
        try {
          parsed = JSON.parse(event.data) as WSEvent;
        } catch {
          return;
        }
        handleEvent(parsed);
      };

      socket.onclose = () => {
        if (cancelled) return;
        setConnectionState("closed");
        const delay = Math.min(1000 * 2 ** retryCountRef.current, 15000);
        retryCountRef.current += 1;
        retryTimeout = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      cancelled = true;
      clearTimeout(retryTimeout);
      socket?.close();
    };
  }, [queryClient]);

  return <LiveFeedContext.Provider value={{ connectionState, events, allEvents }}>{children}</LiveFeedContext.Provider>;
}

export function useLiveFeed(): LiveFeedContextValue {
  return useContext(LiveFeedContext);
}

// Reacts to individual events of the given types, in arrival order (newest
// first), capped at 100 — for consumers that need to drive an animation or a
// transcript off the raw event stream, not just invalidate a query. The call
// view (D5) and graph animation (D1) are why this exists: the invalidation-
// only model above tells a component "something changed," not "here is what
// happened, in order."
export function useLiveEvents(types: WSEventType[]): WSEvent[] {
  const { allEvents } = useLiveFeed();
  return useMemo(() => allEvents.filter((e) => types.includes(e.type)).slice(0, 100), [allEvents, types]);
}
