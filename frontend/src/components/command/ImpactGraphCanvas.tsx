"use client";

import { useEffect, useMemo, useState } from "react";
import { ReactFlow, Background, BackgroundVariant, type Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphNode as GraphNodeModel, ImpactGraph } from "@/lib/types";
import { nodeTypes, type ImpactFlowNode } from "./GraphNode";
import { computeLayout, sortedLayers, LAYER_REVEAL_MS, STATE_EDGE_COLOR } from "./graphVisuals";
import SummaryPanel from "./SummaryPanel";

const REVEAL_EDGE_PORTION = 0.55;
const UNREACHED_EDGE_COLOR = "#22262e";
const ACTIVE_EDGE_COLOR = "#e7e9ec";

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export default function ImpactGraphCanvas({
  graph,
  onNodeClick,
  onWaveComplete,
}: {
  graph: ImpactGraph;
  onNodeClick: (node: GraphNodeModel) => void;
  onWaveComplete?: () => void;
}) {
  const [started, setStarted] = useState(false);
  const [revealedLayer, setRevealedLayer] = useState(-1);
  const [edgeActiveLayer, setEdgeActiveLayer] = useState<number | null>(null);
  const [waveDone, setWaveDone] = useState(false);

  const vendorNode = useMemo(
    () => graph.nodes.find((n) => n.kind === "VENDOR" && n.state === "IMPACTED") ?? graph.nodes.find((n) => n.kind === "VENDOR") ?? graph.nodes[0],
    [graph]
  );

  // The propagation wave (see D1 brief §4): all-healthy -> vendor turns red
  // and pulses -> walk outward layer by layer, each layer's incoming edges
  // getting a travelling-highlight beat before that layer's nodes settle
  // into their real state -> summary panel fades in.
  useEffect(() => {
    let cancelled = false;
    setStarted(false);
    setRevealedLayer(-1);
    setEdgeActiveLayer(null);
    setWaveDone(false);

    async function run() {
      await sleep(60);
      if (cancelled) return;
      setStarted(true);
      await sleep(LAYER_REVEAL_MS);
      if (cancelled) return;

      const layers = sortedLayers(graph.nodes).filter((l) => l !== vendorNode?.layer);
      for (const layer of layers) {
        setEdgeActiveLayer(layer);
        await sleep(LAYER_REVEAL_MS * REVEAL_EDGE_PORTION);
        if (cancelled) return;
        setRevealedLayer(layer);
        setEdgeActiveLayer(null);
        await sleep(LAYER_REVEAL_MS * (1 - REVEAL_EDGE_PORTION));
        if (cancelled) return;
      }
      setWaveDone(true);
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [graph, vendorNode]);

  useEffect(() => {
    if (waveDone) onWaveComplete?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waveDone]);

  const positions = useMemo(() => computeLayout(graph.nodes), [graph.nodes]);

  const flowNodes: ImpactFlowNode[] = useMemo(
    () =>
      graph.nodes.map((node) => {
        const displayed = !started ? "HEALTHY" : node.id === vendorNode?.id ? node.state : node.layer <= revealedLayer ? node.state : "HEALTHY";
        return {
          id: node.id,
          type: node.kind,
          position: positions[node.id] ?? { x: 0, y: 0 },
          data: {
            node: { ...node, state: displayed },
            pulsing: started && node.id === vendorNode?.id,
            onOpen: onNodeClick,
          },
        };
      }),
    [graph.nodes, positions, started, revealedLayer, vendorNode, onNodeClick]
  );

  const flowEdges: Edge[] = useMemo(() => {
    const layerById = new Map(graph.nodes.map((n) => [n.id, n.layer]));
    return graph.edges.map((edge) => {
      const targetLayer = layerById.get(edge.target) ?? 0;
      const isActive = edgeActiveLayer !== null && targetLayer === edgeActiveLayer;
      const isRevealed = targetLayer <= revealedLayer || targetLayer === vendorNode?.layer;
      const color = isRevealed ? STATE_EDGE_COLOR[edge.state] : isActive ? ACTIVE_EDGE_COLOR : UNREACHED_EDGE_COLOR;
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        type: "smoothstep",
        animated: isActive,
        style: {
          stroke: color,
          strokeWidth: isRevealed ? 2 : 1.5,
          opacity: isActive || isRevealed ? 1 : 0.4,
          transition: "stroke 300ms ease, opacity 300ms ease",
        },
      };
    });
  }, [graph.edges, graph.nodes, edgeActiveLayer, revealedLayer, vendorNode]);

  return (
    <div className="relative h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.25 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        zoomOnScroll={false}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#22262e" />
      </ReactFlow>
      <SummaryPanel graph={graph} visible={waveDone} />
    </div>
  );
}
