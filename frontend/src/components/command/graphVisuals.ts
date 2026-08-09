// Shared visual constants for the D1 impact graph (/command). Kept separate
// from the components so the timing constants below are easy to find and
// tune during rehearsal, per the D1 brief.

import type { GraphNode, GraphNodeKind, GraphNodeState } from "@/lib/types";

// ---- Timing (tune these during rehearsal) ----

// Time budget per layer of the propagation wave: half spent animating the
// incoming edges as a travelling highlight, half spent settling that
// layer's nodes into their real state. ~450ms/layer × ~4 layers ≈ the ~2.5s
// the brief asks for.
export const LAYER_REVEAL_MS = 450;

// IDLE -> RUNNING layout transition (left column slide/narrow, canvas
// scale-up). Target ~600ms easeOut per the brief.
export const PHASE_TRANSITION_MS = 600;

// How long the summary panel's exposure figure takes to count up once the
// wave finishes.
export const EXPOSURE_COUNT_UP_MS = 900;

// Fixture mode has no backend pipeline to wait on, so we fake the latency
// before the (fixture) IMPACT_COMPUTED "arrives" — long enough to read as a
// real pipeline run kicking off, short enough not to bore a rehearsal.
export const FIXTURE_IMPACT_DELAY_MS = 1400;

// D2: fake latency before the (fixture) CANDIDATES_FOUND "arrives", measured
// from the moment the propagation wave finishes — sourcing runs after
// diagnosis/exposure in the real pipeline, so the rail should follow the
// graph settling, not race it.
export const FIXTURE_CANDIDATES_DELAY_MS = 900;

// Candidate rail cards stagger in this far apart (framer-motion
// staggerChildren), per the D2 brief.
export const CANDIDATE_STAGGER_MS = 180;

// D3: fake latency before the (fixture) PLAN_PROPOSED "arrives", measured
// from candidates showing up — the solver runs after sourcing narrows the
// field.
export const FIXTURE_PLAN_DELAY_MS = 1100;

// Share of the canvas the graph keeps once the plan diff takes the main area
// (D3 §1: "the graph shrinks further or moves to a corner"). A percentage,
// not a fixed 220px: at that width a four-layer graph rendered as unreadable
// specks, and the approval card — which carries the "Call vendor" button —
// overflowed the column and hid behind the plan panel.
export const GRAPH_CORNER_WIDTH = "38%";

// ---- Layout ----

const LAYER_X_GAP = 260;
const NODE_Y_GAP = 110;

export interface NodePosition {
  x: number;
  y: number;
}

/** Deterministic layered layout: x from `node.layer`, y spread evenly within
 * each layer. No layout library — predictable positions matter more than
 * force-directed prettiness when this is running live on stage. */
export function computeLayout(nodes: GraphNode[]): Record<string, NodePosition> {
  const byLayer = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const list = byLayer.get(node.layer) ?? [];
    list.push(node);
    byLayer.set(node.layer, list);
  }

  const positions: Record<string, NodePosition> = {};
  for (const [layer, list] of byLayer) {
    const totalHeight = (list.length - 1) * NODE_Y_GAP;
    list.forEach((node, i) => {
      positions[node.id] = { x: layer * LAYER_X_GAP, y: i * NODE_Y_GAP - totalHeight / 2 };
    });
  }
  return positions;
}

export function sortedLayers(nodes: GraphNode[]): number[] {
  return [...new Set(nodes.map((n) => n.layer))].sort((a, b) => a - b);
}

// ---- Colour — reuses NetworkMap.tsx's severity palette (the app's
// --color-critical/warning/success/neutral tokens) so the two screens agree
// instead of inventing a second one. ----

export const STATE_STYLE: Record<GraphNodeState, { border: string; text: string; dot: string; ring: string }> = {
  HEALTHY: { border: "border-line-strong", text: "text-ink-muted", dot: "bg-neutral", ring: "shadow-[0_0_0_3px_rgba(101,107,118,0.18)]" },
  AT_RISK: { border: "border-warning/60", text: "text-warning", dot: "bg-warning", ring: "shadow-[0_0_0_3px_rgba(207,154,55,0.22)]" },
  IMPACTED: { border: "border-critical/70", text: "text-critical", dot: "bg-critical", ring: "shadow-[0_0_0_3px_rgba(216,72,77,0.25)]" },
  SUBSTITUTED: { border: "border-success/60", text: "text-success", dot: "bg-success", ring: "shadow-[0_0_0_3px_rgba(63,157,112,0.22)]" },
};

export const STATE_EDGE_COLOR: Record<GraphNodeState, string> = {
  HEALTHY: "#656b76",
  AT_RISK: "#cf9a37",
  IMPACTED: "#d8484d",
  SUBSTITUTED: "#3f9d70",
};

export const KIND_LABEL: Record<GraphNodeKind, string> = {
  VENDOR: "Vendor",
  ITEM: "Item",
  LINE: "Line",
  ORDER: "Order",
  PLANT: "Plant",
};
