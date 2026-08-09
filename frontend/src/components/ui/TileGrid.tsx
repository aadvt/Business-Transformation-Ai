import type { ReactNode } from "react";

export default function TileGrid({ children, minWidth = 220 }: { children: ReactNode; minWidth?: number }) {
  return (
    <div
      className="mb-6 border border-line rounded-lg overflow-hidden grid gap-px bg-line"
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${minWidth}px, 1fr))` }}
    >
      {children}
    </div>
  );
}
