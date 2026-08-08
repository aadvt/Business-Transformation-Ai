"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
} from "react";
import type { ReactNode } from "react";
import {
  INITIAL_AGENTS,
  INITIAL_DISRUPTIONS,
  INITIAL_DUES,
  generateBackups,
  spawnRandomDisruption,
} from "./mockData";
import type { AgentStatus, Disruption, SettlementDue } from "./types";

interface State {
  disruptions: Disruption[];
  dues: SettlementDue[];
  agents: AgentStatus[];
  tick: number;
}

type Action =
  | { type: "TICK" }
  | { type: "APPROVE"; id: string }
  | { type: "REJECT"; id: string }
  | { type: "SETTLE"; ids: string[] };

const initialState: State = {
  disruptions: INITIAL_DISRUPTIONS,
  dues: INITIAL_DUES,
  agents: INITIAL_AGENTS,
  tick: 0,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "TICK": {
      const newDues: SettlementDue[] = [];

      const disruptions = state.disruptions.map((d) => {
        if (d.status === "active") {
          if (d.stageIndex < 2) {
            if (Math.random() < 0.45) {
              return { ...d, stageIndex: d.stageIndex + 1 };
            }
            return d;
          }
          const backups = d.backups.length ? d.backups : generateBackups(d.category);
          return { ...d, backups, status: "awaiting_approval" as const };
        }

        if (d.status === "negotiating") {
          if (Math.random() < 0.55) {
            const nextStage = Math.min(d.stageIndex + 1, 5);
            if (nextStage === 5) {
              const chosen = d.backups[0];
              newDues.push({
                id: `due-${d.id}`,
                vendorId: chosen?.id ?? d.vendorId,
                vendorName: chosen?.name ?? d.vendorName,
                amountINR: d.exposureINR,
                dueDate: "2026-08-31",
                status: "staged",
                sourceDisruptionId: d.id,
              });
              return {
                ...d,
                stageIndex: nextStage,
                status: "settled" as const,
                negotiatedTermsSummary: `${chosen?.name ?? "Backup vendor"} — ${chosen?.etaDays ?? 2} day delivery, ${
                  (chosen?.priceDeltaPct ?? 0) >= 0 ? "+" : ""
                }${chosen?.priceDeltaPct ?? 0}% price, confirmed by voice agent`,
              };
            }
            return { ...d, stageIndex: nextStage };
          }
          return d;
        }

        return d;
      });

      const spawned =
        Math.random() < 0.12 && disruptions.filter((d) => d.status !== "settled" && d.status !== "rejected").length < 6
          ? [spawnRandomDisruption()]
          : [];

      const pendingApprovals = disruptions.filter((d) => d.status === "awaiting_approval").length;
      const negotiatingCount = disruptions.filter((d) => d.status === "negotiating").length;

      const agents = state.agents.map((a) => {
        if (a.id === "governance") {
          return {
            ...a,
            state: pendingApprovals > 0 ? ("alert" as const) : ("idle" as const),
            detail: pendingApprovals > 0 ? `${pendingApprovals} approval${pendingApprovals > 1 ? "s" : ""} pending` : "All clear",
          };
        }
        if (a.id === "negotiation") {
          return {
            ...a,
            state: negotiatingCount > 0 ? ("working" as const) : ("idle" as const),
            detail: negotiatingCount > 0 ? `On ${negotiatingCount} live call${negotiatingCount > 1 ? "s" : ""}` : "Idle",
          };
        }
        return a;
      });

      return {
        disruptions: [...disruptions, ...spawned],
        dues: [...state.dues, ...newDues],
        agents,
        tick: state.tick + 1,
      };
    }

    case "APPROVE": {
      return {
        ...state,
        disruptions: state.disruptions.map((d) =>
          d.id === action.id && d.status === "awaiting_approval"
            ? { ...d, status: "negotiating" as const, stageIndex: 3 }
            : d
        ),
      };
    }

    case "REJECT": {
      return {
        ...state,
        disruptions: state.disruptions.map((d) =>
          d.id === action.id && d.status === "awaiting_approval" ? { ...d, status: "rejected" as const } : d
        ),
      };
    }

    case "SETTLE": {
      return {
        ...state,
        dues: state.dues.map((due) => (action.ids.includes(due.id) ? { ...due, status: "settled" as const } : due)),
      };
    }

    default:
      return state;
  }
}

interface SanjeevaniContextValue {
  disruptions: Disruption[];
  dues: SettlementDue[];
  agents: AgentStatus[];
  totalOpenExposureINR: number;
  pendingApprovalsCount: number;
  approve: (id: string) => void;
  reject: (id: string) => void;
  settle: (ids: string[]) => void;
}

const SanjeevaniContext = createContext<SanjeevaniContextValue | null>(null);

export function SanjeevaniProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const interval = setInterval(() => dispatch({ type: "TICK" }), 3200);
    return () => clearInterval(interval);
  }, []);

  const approve = useCallback((id: string) => dispatch({ type: "APPROVE", id }), []);
  const reject = useCallback((id: string) => dispatch({ type: "REJECT", id }), []);
  const settle = useCallback((ids: string[]) => dispatch({ type: "SETTLE", ids }), []);

  const totalOpenExposureINR = useMemo(
    () =>
      state.disruptions
        .filter((d) => d.status !== "settled" && d.status !== "rejected")
        .reduce((sum, d) => sum + d.exposureINR, 0),
    [state.disruptions]
  );

  const pendingApprovalsCount = useMemo(
    () => state.disruptions.filter((d) => d.status === "awaiting_approval").length,
    [state.disruptions]
  );

  const value: SanjeevaniContextValue = {
    disruptions: state.disruptions,
    dues: state.dues,
    agents: state.agents,
    totalOpenExposureINR,
    pendingApprovalsCount,
    approve,
    reject,
    settle,
  };

  return <SanjeevaniContext.Provider value={value}>{children}</SanjeevaniContext.Provider>;
}

export function useSanjeevani(): SanjeevaniContextValue {
  const ctx = useContext(SanjeevaniContext);
  if (!ctx) throw new Error("useSanjeevani must be used within SanjeevaniProvider");
  return ctx;
}
