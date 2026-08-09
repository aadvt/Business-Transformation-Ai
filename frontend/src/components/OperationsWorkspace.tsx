"use client";

import dynamic from "next/dynamic";
import CommandDeck from "@/components/CommandDeck";

const NetworkMap = dynamic(() => import("@/components/NetworkMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center bg-surface-2 text-[13px] text-ink-muted">
      Loading supply network…
    </div>
  ),
});

/* The operations dashboard is the map. Everything else floats over it, so the
   operator never trades away the view of the network to read a number.
   `data-fullbleed` is what tells the shell to drop its content padding for
   this one route — see globals.css. */
export default function OperationsWorkspace() {
  return (
    <div
      data-fullbleed
      className="relative h-[calc(100vh-var(--shell-header,48px))] w-full overflow-hidden"
    >
      <NetworkMap variant="bleed" />
      <CommandDeck />
    </div>
  );
}
