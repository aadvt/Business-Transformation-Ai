"use client";

import { useEffect, useRef, useState, type RefObject } from "react";

interface Point {
  x: number;
  y: number;
}

// Draws a dashed line from the hovered candidate rail card into the
// impacted ITEM node(s) on the graph — plain DOM measurement + an overlay
// SVG rather than a React Flow custom edge, since the rail lives outside
// the canvas entirely. Re-measures every frame while hovering so it stays
// attached if the canvas is panned mid-hover.
export default function GhostEdgeOverlay({
  containerRef,
  hoveredCandidateId,
  targetNodeIds,
}: {
  containerRef: RefObject<HTMLDivElement | null>;
  hoveredCandidateId: string | null;
  targetNodeIds: string[];
}) {
  const [paths, setPaths] = useState<{ from: Point; to: Point }[]>([]);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (!hoveredCandidateId) {
      setPaths([]);
      return;
    }

    function measure() {
      const container = containerRef.current;
      const cardEl = hoveredCandidateId ? document.getElementById(`candidate-card-${hoveredCandidateId}`) : null;
      if (!container || !cardEl) {
        rafRef.current = requestAnimationFrame(measure);
        return;
      }

      const containerRect = container.getBoundingClientRect();
      const cardRect = cardEl.getBoundingClientRect();
      const from: Point = { x: cardRect.left - containerRect.left, y: cardRect.top - containerRect.top + cardRect.height / 2 };

      const next: { from: Point; to: Point }[] = [];
      for (const nodeId of targetNodeIds) {
        const nodeEl = container.querySelector(`[data-id="${nodeId}"]`);
        if (!nodeEl) continue;
        const nodeRect = nodeEl.getBoundingClientRect();
        next.push({
          from,
          to: { x: nodeRect.right - containerRect.left, y: nodeRect.top - containerRect.top + nodeRect.height / 2 },
        });
      }
      setPaths(next);
      rafRef.current = requestAnimationFrame(measure);
    }

    rafRef.current = requestAnimationFrame(measure);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [hoveredCandidateId, targetNodeIds, containerRef]);

  if (paths.length === 0) return null;

  return (
    <svg className="pointer-events-none absolute inset-0 z-20 h-full w-full overflow-visible">
      {paths.map((p, i) => (
        <path
          key={i}
          d={`M ${p.from.x} ${p.from.y} C ${(p.from.x + p.to.x) / 2} ${p.from.y}, ${(p.from.x + p.to.x) / 2} ${p.to.y}, ${p.to.x} ${p.to.y}`}
          fill="none"
          stroke="#cf9a37"
          strokeWidth={2}
          strokeDasharray="6 4"
          className="animate-ghost-dash"
        />
      ))}
    </svg>
  );
}
