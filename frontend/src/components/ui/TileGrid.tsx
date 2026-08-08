import type { ReactNode } from "react";

export default function TileGrid({ children, minWidth = 220 }: { children: ReactNode; minWidth?: number }) {
  return (
    <div
      className="mb-8 grid gap-3"
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${minWidth}px, 1fr))` }}
    >
      {children}
    </div>
  );
}
