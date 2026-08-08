"use client";

import dynamic from "next/dynamic";
import PageHeader from "@/components/PageHeader";

const NetworkMap = dynamic(() => import("@/components/NetworkMap"), {
  ssr: false,
  loading: () => (
    <div className="glass-panel flex h-full items-center justify-center rounded-2xl text-sm text-ink-muted">
      Loading map…
    </div>
  ),
});

export default function NetworkPage() {
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Network"
        subtitle="Vendors as nodes, animated flow along active disruptions, edge colour by severity."
      />
      <div className="h-[76vh] min-h-[520px]">
        <NetworkMap />
      </div>
    </div>
  );
}
