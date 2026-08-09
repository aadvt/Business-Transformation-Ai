"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Zap } from "lucide-react";
import { toast } from "sonner";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";
import DisruptionRow from "@/components/DisruptionRow";
import AgentStatusStrip from "@/components/AgentStatusStrip";
import Spinner from "@/components/ui/Spinner";
import { Button } from "@/components/ui/button";
import { useAgentsStatus, useDisruptions, useSimulateDisruption } from "@/lib/queries";
import { useLiveEvents } from "@/lib/live";
import { api } from "@/lib/api";
import { impactGraphFixture, planFixture } from "@/lib/demoFixtures";
import { candidatesFixture } from "@/lib/directoryFixtures";
import type { ApprovalDecision, CallSession, GraphNode, ImpactGraph, Plan, ScenarioKind, SourcingCandidate, WSEvent } from "@/lib/types";
import SimulateDialog from "@/components/command/SimulateDialog";
import ImpactGraphCanvas from "@/components/command/ImpactGraphCanvas";
import NodeDetailDialog from "@/components/command/NodeDetailDialog";
import CandidateRail from "@/components/command/CandidateRail";
import GhostEdgeOverlay from "@/components/command/GhostEdgeOverlay";
import PlanDiffPanel from "@/components/command/PlanDiffPanel";
import ApprovalStatusCard from "@/components/command/ApprovalStatusCard";
import CallView from "@/components/command/CallView";
import {
  FIXTURE_CANDIDATES_DELAY_MS,
  FIXTURE_IMPACT_DELAY_MS,
  FIXTURE_PLAN_DELAY_MS,
  GRAPH_CORNER_WIDTH,
  PHASE_TRANSITION_MS,
} from "@/components/command/graphVisuals";

// Everything on this route works fully against D0/D2's fixtures until the
// real backend endpoints exist — see api.ts's USE_FIXTURES gate.
const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "true";
const DEMO_CONTROLS = process.env.NEXT_PUBLIC_DEMO_CONTROLS === "true";

type Phase = "idle" | "running" | "resolved";

const LEFT_WIDTH: Record<Phase, number> = { idle: 320, running: 208, resolved: 208 };
const TRANSITION = { duration: PHASE_TRANSITION_MS / 1000, ease: "easeOut" as const };

// DemoControlBar's numbered jump buttons and 1-7 keyboard shortcuts push
// /command?d=<id>&mode=<mode> — this is the recovery path the D5b brief asks
// for ("the operator must be able to recover on stage without a terminal").
// Each mode implies everything before it in the flow, so restoring mode
// "plan" also (re)populates the graph and candidates, not just the plan.
const MODE_ORDER = ["ingest", "briefing", "impact", "candidates", "plan", "call", "outcome"] as const;
type ModeName = (typeof MODE_ORDER)[number];

export default function CommandPage() {
  return (
    <Suspense fallback={<div className="flex h-[76vh] min-h-[560px] items-center justify-center"><Spinner size={18} label="Loading…" /></div>}>
      <CommandPageInner />
    </Suspense>
  );
}

function CommandPageInner() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogDefaultScenario, setDialogDefaultScenario] = useState<ScenarioKind>("DELAYED");
  const [disruptionId, setDisruptionId] = useState<string | null>(null);
  const [graph, setGraph] = useState<ImpactGraph | null>(null);
  const [handledEventId, setHandledEventId] = useState<string | null>(null);
  const [waveDone, setWaveDone] = useState(false);
  const [candidates, setCandidates] = useState<SourcingCandidate[] | null>(null);
  const [handledCandidatesEventId, setHandledCandidatesEventId] = useState<string | null>(null);
  const [hoveredCandidateId, setHoveredCandidateId] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [handledPlanEventId, setHandledPlanEventId] = useState<string | null>(null);
  const [approvalDecision, setApprovalDecision] = useState<ApprovalDecision | null>(null);
  const [handledApprovalEventId, setHandledApprovalEventId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [sheetSyncStatus, setSheetSyncStatus] = useState<"SYNCED" | "UNAVAILABLE" | "PENDING">("PENDING");
  const [callSession, setCallSession] = useState<CallSession | null>(null);
  const [callStarting, setCallStarting] = useState(false);

  const canvasRootRef = useRef<HTMLDivElement>(null);
  const searchParams = useSearchParams();

  const { data: disruptionsData } = useDisruptions();
  const { data: agentsResponse } = useAgentsStatus();
  const simulate = useSimulateDisruption();
  const impactEvents = useLiveEvents(["IMPACT_COMPUTED"]);
  const candidatesEvents = useLiveEvents(["CANDIDATES_FOUND"]);
  const planEvents = useLiveEvents(["PLAN_PROPOSED"]);
  const approvalEvents = useLiveEvents(["APPROVAL_DECIDED"]);

  const recent = [...(disruptionsData?.items ?? [])].sort(
    (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
  );

  const impactedItemNodeIds = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.kind === "ITEM" && n.state === "IMPACTED").map((n) => n.id) : []),
    [graph]
  );

  const handleImpactEvent = useCallback((event: Pick<WSEvent, "event_id" | "disruption_id">) => {
    if (!event.disruption_id) return;
    setHandledEventId(event.event_id);
    setDisruptionId(event.disruption_id);
    api.getImpactGraph(event.disruption_id).then(setGraph);
  }, []);

  // The live feed replays its last 50 events on connect, so the newest
  // CANDIDATES_FOUND/PLAN_PROPOSED/IMPACT_COMPUTED in hand may belong to an
  // earlier run. Acting on one paints the previous disruption's graph and
  // candidates onto this run. Events with no disruption_id stay allowed —
  // fixture mode synthesises those.
  const isForCurrentRun = useCallback(
    (eventDisruptionId: string | null | undefined) =>
      !disruptionId || !eventDisruptionId || eventDisruptionId === disruptionId,
    [disruptionId]
  );

  const handleCandidatesEvent = useCallback(
    (event: Pick<WSEvent, "event_id" | "disruption_id">) => {
      setHandledCandidatesEventId(event.event_id);
      if (USE_FIXTURES) {
        setCandidates(candidatesFixture);
        return;
      }
      if (!event.disruption_id) return;
      // Store null rather than [] when sourcing found nothing: [] is truthy,
      // so an empty result would latch permanently — the retry guards below
      // read `candidates` as "already have them" and never look again, which
      // is what silently withheld the "Call vendor" button.
      api.getDisruption(event.disruption_id).then((d) => setCandidates(d.candidates.length > 0 ? d.candidates : null));
    },
    []
  );

  // Fixture mode: fake IMPACT_COMPUTED on a timer, since there's no real
  // pipeline to emit one — everything downstream (fetch + wave) is
  // identical to the real-event path below.
  useEffect(() => {
    if (!USE_FIXTURES || phase !== "running" || graph) return;
    const timeout = setTimeout(() => {
      handleImpactEvent({ event_id: `fixture-${Date.now()}`, disruption_id: impactGraphFixture.disruption_id });
    }, FIXTURE_IMPACT_DELAY_MS);
    return () => clearTimeout(timeout);
  }, [phase, graph, handleImpactEvent]);

  // Real mode: react to the live WS feed. The three-click trigger (§2 of
  // the D1 brief) never awaits `simulateDisruption`'s response — the canvas
  // reacts the instant IMPACT_COMPUTED actually arrives, 30-90s later.
  useEffect(() => {
    if (USE_FIXTURES || phase !== "running" || graph) return;
    const latest = impactEvents[0];
    if (!latest || latest.event_id === handledEventId) return;
    if (!isForCurrentRun(latest.disruption_id)) return;
    handleImpactEvent(latest);
  }, [impactEvents, phase, graph, handledEventId, handleImpactEvent, isForCurrentRun]);

  // Fixture mode: fake CANDIDATES_FOUND shortly after the wave settles —
  // sourcing runs after diagnosis in the real pipeline, so the rail
  // shouldn't race the graph.
  useEffect(() => {
    if (!USE_FIXTURES || !waveDone || candidates) return;
    const timeout = setTimeout(() => {
      handleCandidatesEvent({ event_id: `fixture-candidates-${Date.now()}`, disruption_id: disruptionId });
    }, FIXTURE_CANDIDATES_DELAY_MS);
    return () => clearTimeout(timeout);
  }, [waveDone, candidates, disruptionId, handleCandidatesEvent]);

  // Real mode: this event type already exists in the live feed (D0).
  useEffect(() => {
    if (USE_FIXTURES || !graph || candidates) return;
    const latest = candidatesEvents[0];
    if (!latest || latest.event_id === handledCandidatesEventId) return;
    if (!isForCurrentRun(latest.disruption_id)) return;
    handleCandidatesEvent(latest);
  }, [candidatesEvents, graph, candidates, handledCandidatesEventId, handleCandidatesEvent, isForCurrentRun]);

  const handlePlanEvent = useCallback((event: Pick<WSEvent, "event_id" | "disruption_id">) => {
    setHandledPlanEventId(event.event_id);
    if (USE_FIXTURES) {
      setPlan(planFixture);
      return;
    }
    if (!event.disruption_id) return;
    api.getPlan(event.disruption_id).then(setPlan);
  }, []);

  // Fixture mode: fake PLAN_PROPOSED shortly after candidates show up — the
  // solver runs after sourcing narrows the field.
  useEffect(() => {
    if (!USE_FIXTURES || !candidates || plan) return;
    const timeout = setTimeout(() => {
      handlePlanEvent({ event_id: `fixture-plan-${Date.now()}`, disruption_id: disruptionId });
    }, FIXTURE_PLAN_DELAY_MS);
    return () => clearTimeout(timeout);
  }, [candidates, plan, disruptionId, handlePlanEvent]);

  // Real mode: this event type already exists in the live feed (D0).
  useEffect(() => {
    if (USE_FIXTURES || !candidates || plan) return;
    const latest = planEvents[0];
    if (!latest || latest.event_id === handledPlanEventId) return;
    if (!isForCurrentRun(latest.disruption_id)) return;
    handlePlanEvent(latest);
  }, [planEvents, candidates, plan, handledPlanEventId, handlePlanEvent, isForCurrentRun]);

  // D4: reacts to APPROVAL_DECIDED regardless of fixture/real mode — in
  // fixture mode this arrives via fixtureBus (see live.tsx), which /phone's
  // Approve/Modify tap publishes to from a *separate browser tab*; in real
  // mode both tabs share the same backend WS. Either way this effect is
  // identical, which is the whole point of routing fixture events through
  // the same useLiveEvents pipeline as real ones.
  useEffect(() => {
    const latest = approvalEvents[0];
    if (!latest || latest.event_id === handledApprovalEventId) return;
    if (disruptionId && latest.disruption_id && latest.disruption_id !== disruptionId) return;

    setHandledApprovalEventId(latest.event_id);
    const payload = latest.payload as { decision?: ApprovalDecision };
    if (!payload.decision) return;
    setApprovalDecision(payload.decision);
    toast[payload.decision === "APPROVE" ? "success" : "info"](
      payload.decision === "APPROVE" ? "Approved by owner via WhatsApp" : "Owner requested other options via WhatsApp"
    );
  }, [approvalEvents, handledApprovalEventId, disruptionId]);

  function openTrigger(defaultScenario: ScenarioKind) {
    setDialogDefaultScenario(defaultScenario);
    setDialogOpen(true);
  }

  // Pull the whole current state of a disruption onto the canvas in one go.
  // Used when a trigger doesn't start a fresh run (the vendor already has an
  // open disruption, so the backend re-runs nothing and emits no events) and
  // for ?call= refresh recovery. Without it the canvas waits forever on
  // events that already fired.
  const hydrateFromDisruption = useCallback(async (id: string) => {
    setDisruptionId(id);
    const [detail, impact] = await Promise.all([
      api.getDisruption(id).catch(() => null),
      api.getImpactGraph(id).catch(() => null),
    ]);
    if (impact) setGraph(impact);
    if (detail?.candidates.length) setCandidates(detail.candidates);
    if (detail?.approval?.status === "APPROVED") setApprovalDecision("APPROVE");
    const nextPlan = await api.getPlan(id).catch(() => null);
    if (nextPlan) setPlan(nextPlan);
    setWaveDone(true);
    setPhase("resolved");
  }, []);

  function handleSubmit(body: { vendor_id: string; kind: ScenarioKind; effective_date: string }) {
    simulate.mutate(body, {
      onSuccess: (result) => {
        // newly_triggered=false means this vendor already had an open
        // disruption and the pipeline did not re-run — catch the canvas up to
        // where that disruption actually is instead of spinning.
        if (result.newly_triggered === false && result.disruption_id) {
          toast.info("That vendor already has an open disruption — showing where it stands.");
          hydrateFromDisruption(result.disruption_id);
        }
      },
    });
    setDialogOpen(false);
    setDisruptionId(null);
    setGraph(null);
    setHandledEventId(null);
    setWaveDone(false);
    setCandidates(null);
    setHandledCandidatesEventId(null);
    setHoveredCandidateId(null);
    setPlan(null);
    setHandledPlanEventId(null);
    setApprovalDecision(null);
    setHandledApprovalEventId(null);
    setPhase("running");
    setSheetSyncStatus("PENDING");
  }

  function syncAgentSheet() {
    setSheetSyncStatus("PENDING");
    api.syncAgentSheet(disruptionId ?? undefined).then((result) => setSheetSyncStatus(result.status)).catch(() => setSheetSyncStatus("UNAVAILABLE"));
  }

  // Refresh recovery for the call: /command?call=<id> restores the call view
  // mid-flow (CallView itself refetches the session and re-renders whatever
  // already happened).
  useEffect(() => {
    const callParam = new URLSearchParams(window.location.search).get("call");
    if (callParam && !callSession) {
      api.getCall(callParam).then((c) => {
        setCallSession(c);
        setPhase("resolved");
        if (c.disruption_id) hydrateFromDisruption(c.disruption_id);
      }).catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Restores whatever stage `mode` names, instantly (fixtures) or by
  // re-fetching (real backend) — each mode implies everything before it, so
  // jumping straight to "plan" also brings the graph and candidates back.
  // Never auto-dials a real call: in real mode, "call"/"outcome" only render
  // whatever the existing `?call=` param already resolved above — the
  // operator still has to press "Call vendor" themselves. Fixture mode has
  // no real phone to worry about, so it auto-starts a scripted replay call.
  useEffect(() => {
    const mode = searchParams.get("mode") as ModeName | null;
    if (!mode || !MODE_ORDER.includes(mode)) return;
    const d = searchParams.get("d");
    if (d && d !== disruptionId) setDisruptionId(d);
    const targetId = d ?? disruptionId ?? impactGraphFixture.disruption_id;
    const idx = MODE_ORDER.indexOf(mode);

    if (idx === 0) {
      setPhase("idle");
      return;
    }
    setPhase("running");
    if (idx === MODE_ORDER.indexOf("briefing")) {
      if (USE_FIXTURES) setSheetSyncStatus("SYNCED");
      else syncAgentSheet();
      return;
    }

    setPhase("resolved");
    if (!graph) {
      if (USE_FIXTURES) {
        setDisruptionId(impactGraphFixture.disruption_id);
        setGraph(impactGraphFixture);
      } else {
        api.getImpactGraph(targetId).then(setGraph).catch(() => undefined);
      }
    }
    if (idx >= MODE_ORDER.indexOf("candidates") && !candidates) {
      if (USE_FIXTURES) setCandidates(candidatesFixture);
      else api.getDisruption(targetId).then((dd) => setCandidates(dd.candidates)).catch(() => undefined);
    }
    if (idx >= MODE_ORDER.indexOf("plan") && !plan) {
      if (USE_FIXTURES) setPlan(planFixture);
      else api.getPlan(targetId).then(setPlan).catch(() => undefined);
    }
    if (idx >= MODE_ORDER.indexOf("call") && USE_FIXTURES && !callSession && !callStarting) {
      setCallStarting(true);
      api
        .startCall({ disruption_id: targetId, vendor_id: candidatesFixture[0].vendor_id, mode: "REPLAY" })
        .then((c) => {
          setCallSession(c);
          const url = new URL(window.location.href);
          url.searchParams.set("call", c.id);
          window.history.replaceState(null, "", url.toString());
        })
        .finally(() => setCallStarting(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function startCall(mode: "LIVE" | "REPLAY") {
    const winner = candidates?.[0];
    if (!winner || !disruptionId || callStarting) return;
    setCallStarting(true);
    api
      .startCall({ disruption_id: disruptionId, vendor_id: winner.vendor_id, mode })
      .then((c) => {
        setCallSession(c);
        const url = new URL(window.location.href);
        url.searchParams.set("call", c.id);
        window.history.replaceState(null, "", url.toString());
      })
      .catch((err) => toast.error(`Could not start the call: ${err.message}`))
      .finally(() => setCallStarting(false));
  }

  return (
    // Fill the viewport rather than a fixed 76vh: the canvas has to hold a
    // 4-layer graph, the candidate rail and the plan diff at the same time,
    // and 76vh left every one of them scrolling in a letterbox.
    <div className="flex h-[calc(100vh-7.5rem)] min-h-[640px] flex-col gap-3">
      <PageHeader
        title="Command"
        subtitle="Trigger a disruption and watch the blast radius propagate through the supply network."
        actions={
          phase === "idle" && (
            <div className="flex gap-2">
              {DEMO_CONTROLS && <Button variant="secondary" onClick={syncAgentSheet}>Sync vendor sheet</Button>}
              <Button variant="secondary" icon={<Zap size={14} />} onClick={() => openTrigger("DELAYED")}>
                Simulate Crisis
              </Button>
              <Button variant="destructive" icon={<AlertTriangle size={14} />} onClick={() => openTrigger("BACKED_OUT")}>
                Simulate Vendor Backout
              </Button>
            </div>
          )
        }
      />

      <AnimatePresence>
        {phase !== "idle" && agentsResponse && (
          <motion.div
            key="stage-strip"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={TRANSITION}
            className="overflow-hidden"
          >
            <AgentStatusStrip agents={agentsResponse.agents} />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex min-h-0 flex-1 gap-4">
        <motion.div layout transition={TRANSITION} style={{ width: LEFT_WIDTH[phase] }} className="shrink-0 overflow-y-auto">
          <SectionHeading count={recent.length}>Recent disruptions</SectionHeading>
          {recent.length === 0 ? (
            <EmptyState>Nothing yet.</EmptyState>
          ) : (
            recent.slice(0, phase === "idle" ? 10 : 5).map((d) => <DisruptionRow key={d.id} disruption={d} />)
          )}
        </motion.div>

        <motion.div layout transition={TRANSITION} ref={canvasRootRef} className="panel-flush relative flex min-w-0 flex-1 overflow-hidden">
          <motion.div
            layout
            transition={TRANSITION}
            className="relative h-full shrink-0"
            style={{ width: plan ? GRAPH_CORNER_WIDTH : candidates ? "65%" : "100%" }}
          >
            <AnimatePresence mode="wait">
              {phase === "idle" && (
                <motion.div
                  key="idle"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex h-full items-center justify-center px-6"
                >
                  <EmptyState>Trigger a simulation above to see the blast radius.</EmptyState>
                </motion.div>
              )}

              {phase !== "idle" && !graph && (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex h-full items-center justify-center"
                >
                  <Spinner size={18} label="Pipeline running…" />
                </motion.div>
              )}

              {graph && (
                <motion.div
                  key="graph"
                  initial={{ opacity: 0, scale: 0.92 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={TRANSITION}
                  className="h-full w-full"
                >
                  <ImpactGraphCanvas
                    graph={graph}
                    compact={Boolean(plan)}
                    onNodeClick={setSelectedNode}
                    onWaveComplete={() => {
                      setPhase("resolved");
                      setWaveDone(true);
                    }}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {phase === "resolved" && (
                <motion.div
                  key="approval"
                  initial={{ x: 48, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  exit={{ x: 48, opacity: 0 }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                  // z-10 keeps it above the plan panel: this card carries the
                  // "Call vendor" button, so it must never end up underneath
                  // a sibling that mounts later.
                  className="absolute bottom-4 left-4 z-10 w-[280px]"
                >
                  <ApprovalStatusCard
                    decision={approvalDecision}
                    vendorName={candidates?.[0]?.name}
                    onCallVendor={candidates && candidates.length > 0 && !callSession ? startCall : undefined}
                    callStarting={callStarting}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          <AnimatePresence mode="wait">
            {plan ? (
              <motion.div
                key="plan-diff"
                initial={{ x: 48, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: 48, opacity: 0 }}
                transition={TRANSITION}
                className="h-full min-w-0 flex-1 border-l border-line"
              >
                <PlanDiffPanel plan={plan} />
              </motion.div>
            ) : (
              candidates &&
              candidates.length > 0 && (
                <motion.div
                  key="candidate-rail"
                  initial={{ x: 48, opacity: 0 }}
                  animate={{ x: 0, opacity: 1 }}
                  exit={{ x: 48, opacity: 0 }}
                  transition={TRANSITION}
                  className="h-full w-[35%] shrink-0 border-l border-line"
                >
                  <CandidateRail
                    candidates={candidates}
                    onHoverCandidate={setHoveredCandidateId}
                    syncStatus={sheetSyncStatus}
                    onSync={syncAgentSheet}
                    csvUrl={api.getAgentSheetCsvUrl(disruptionId ?? undefined)}
                  />
                </motion.div>
              )
            )}
          </AnimatePresence>

          <GhostEdgeOverlay containerRef={canvasRootRef} hoveredCandidateId={hoveredCandidateId} targetNodeIds={impactedItemNodeIds} />

          {/* D5b: the call takes over the whole canvas as a full-bleed mode —
              a layout takeover inside /command, never a route change. */}
          <AnimatePresence>
            {callSession && (
              <motion.div
                key="call-mode"
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.45, ease: "easeOut" }}
                className="absolute inset-0 z-20 bg-surface"
              >
                <CallView callId={callSession.id} initial={callSession} plan={plan} />
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </div>

      <SimulateDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        defaultScenario={dialogDefaultScenario}
        onSubmit={handleSubmit}
        submitting={simulate.isPending}
      />
      <NodeDetailDialog node={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
