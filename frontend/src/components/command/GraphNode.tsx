"use client";

import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import { Building2, ClipboardList, Factory, Package, Truck } from "lucide-react";
import clsx from "clsx";
import type { GraphNode as GraphNodeModel, GraphNodeKind } from "@/lib/types";
import { KIND_LABEL, STATE_STYLE } from "./graphVisuals";

const KIND_ICON: Record<GraphNodeKind, typeof Truck> = {
  VENDOR: Truck,
  ITEM: Package,
  LINE: Factory,
  ORDER: ClipboardList,
  PLANT: Building2,
};

export interface ImpactNodeData extends Record<string, unknown> {
  node: GraphNodeModel;
  pulsing: boolean;
  onOpen: (node: GraphNodeModel) => void;
}

export type ImpactFlowNode = Node<ImpactNodeData, GraphNodeKind>;

// One shared base card, registered per GraphNodeKind in nodeTypes (see
// ImpactGraphCanvas) — the kind only changes the icon, everything else
// (state colour, badges, click-through) is identical.
function GraphNodeCard({ data }: NodeProps<ImpactFlowNode>) {
  const { node, pulsing, onOpen } = data;
  const style = STATE_STYLE[node.state];
  const Icon = KIND_ICON[node.kind];

  return (
    <div
      onClick={() => onOpen(node)}
      className={clsx(
        "w-[168px] cursor-pointer rounded-lg border bg-surface px-3 py-2.5 shadow-panel transition-[border-color,box-shadow,color] duration-300",
        style.border,
        style.ring,
        pulsing && "animate-node-pulse"
      )}
    >
      <Handle type="target" position={Position.Left} className="!opacity-0" />
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className={clsx("h-1.5 w-1.5 shrink-0 rounded-full", style.dot)} />
        <Icon size={12} className="shrink-0 text-ink-faint" />
        <span className="eyebrow truncate">{KIND_LABEL[node.kind]}</span>
      </div>
      <p className="truncate text-[13px] font-medium text-ink">{node.label}</p>
      {node.badges.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {node.badges.slice(0, 3).map((badge) => (
            <span key={badge} className="rounded-sm bg-surface-2 px-1.5 py-px text-[10px] text-ink-muted">
              {badge}
            </span>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Right} className="!opacity-0" />
    </div>
  );
}

export const nodeTypes: Record<GraphNodeKind, typeof GraphNodeCard> = {
  VENDOR: GraphNodeCard,
  ITEM: GraphNodeCard,
  LINE: GraphNodeCard,
  ORDER: GraphNodeCard,
  PLANT: GraphNodeCard,
};
