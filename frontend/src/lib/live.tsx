"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { wsUrl } from "./api";
import type { WSEvent, WSEventType } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

interface LiveFeedContextValue {
  connectionState: ConnectionState;
  events: WSEvent[];
}

const LiveFeedContext = createContext<LiveFeedContextValue>({ connectionState: "connecting", events: [] });

// Which query key prefixes to invalidate when each WS event type arrives.
// Prefix arrays match React Query's default (non-exact) invalidation, so
// e.g. ["disruptions"] also invalidates ["disruptions", "AWAITING_APPROVAL"].
const EVENT_INVALIDATIONS: Partial<Record<WSEventType, string[][]>> = {
  AGENT_STATUS_CHANGED: [["agentsStatus"]],
  DISRUPTION_CREATED: [["disruptions"], ["dashboardSummary"]],
  STAGE_CHANGED: [["disruptions"], ["disruption"], ["dashboardSummary"]],
  EXPOSURE_COMPUTED: [["disruption"], ["dashboardSummary"]],
  CANDIDATES_FOUND: [["disruption"]],
  APPROVAL_REQUESTED: [["disruptions"], ["disruption"], ["dashboardSummary"]],
  APPROVAL_DECIDED: [["disruptions"], ["disruption"], ["dashboardSummary"]],
  NEGOTIATION_UPDATE: [["disruption"], ["disruptions"]],
  SETTLEMENT_STAGED: [["settlementBatches"], ["dashboardSummary"]],
};

const MAX_EVENTS = 50;

export function LiveFeedProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [events, setEvents] = useState<WSEvent[]>([]);
  const retryCountRef = useRef(0);

  useEffect(() => {
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

        if (parsed.type !== "HEARTBEAT") {
          setEvents((prev) => [parsed, ...prev].slice(0, MAX_EVENTS));
        }

        for (const key of EVENT_INVALIDATIONS[parsed.type] ?? []) {
          queryClient.invalidateQueries({ queryKey: key });
        }
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

  return <LiveFeedContext.Provider value={{ connectionState, events }}>{children}</LiveFeedContext.Provider>;
}

export function useLiveFeed(): LiveFeedContextValue {
  return useContext(LiveFeedContext);
}
