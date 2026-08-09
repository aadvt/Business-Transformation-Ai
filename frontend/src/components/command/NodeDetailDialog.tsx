"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { GraphNode } from "@/lib/types";
import { KIND_LABEL, STATE_STYLE } from "./graphVisuals";

function formatDetailValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDetailKey(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function NodeDetailDialog({ node, onClose }: { node: GraphNode | null; onClose: () => void }) {
  const detailEntries = node?.detail ? Object.entries(node.detail) : [];

  return (
    <Dialog open={node !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {node && (
          <>
            <DialogHeader>
              <span className={`eyebrow mb-0.5 ${STATE_STYLE[node.state].text}`}>
                {KIND_LABEL[node.kind]} · {node.state.replace("_", " ")}
              </span>
              <DialogTitle>{node.label}</DialogTitle>
              <DialogDescription>Layer {node.layer}</DialogDescription>
            </DialogHeader>

            {node.badges.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {node.badges.map((badge) => (
                  <span key={badge} className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-muted">
                    {badge}
                  </span>
                ))}
              </div>
            )}

            {detailEntries.length === 0 ? (
              <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-[13px] text-ink-faint">
                No additional detail for this node.
              </p>
            ) : (
              <dl className="panel-flush divide-y divide-line">
                {detailEntries.map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between gap-4 px-3 py-2 text-[13px]">
                    <dt className="text-ink-muted">{formatDetailKey(key)}</dt>
                    <dd className="numeric text-right text-ink">{formatDetailValue(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
