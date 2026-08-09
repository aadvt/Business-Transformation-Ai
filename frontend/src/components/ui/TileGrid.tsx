import type { ReactNode } from "react";

/* A plain track, not a container. Its children are already self-contained
   cards in this system, so giving the grid its own border, grout and shadow
   would nest a card inside a card (and show grey wedges through the tiles'
   rounded corners). Separation here is spacing, nothing else. */
export default function TileGrid({ children, minWidth = 220 }: { children: ReactNode; minWidth?: number }) {
  return (
    <div
      className="mb-6 grid gap-4"
      style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${minWidth}px, 1fr))` }}
    >
      {children}
    </div>
  );
}
