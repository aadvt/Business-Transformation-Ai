"use client";

import { useSanjeevani } from "@/lib/store";
import AgentStatusStrip from "@/components/AgentStatusStrip";
import WaterfallPipeline from "@/components/WaterfallPipeline";

export default function WaterfallPage() {
  const { disruptions, agents } = useSanjeevani();

  const sorted = [...disruptions].sort((a, b) => {
    const rank = (s: string) => (s === "awaiting_approval" ? 0 : s === "negotiating" ? 1 : s === "active" ? 2 : s === "settled" ? 3 : 4);
    return rank(a.status) - rank(b.status) || new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime();
  });

  return (
    <div>
      <h1 className="sanjeevani-page-title">Live Pipeline</h1>
      <p className="sanjeevani-page-subtitle">
        Sensing &rarr; Diagnosis &rarr; Sourcing &rarr; Negotiation &rarr; Governance &rarr; Settlement, tracked per disruption in real time.
      </p>

      <AgentStatusStrip agents={agents} />

      <div>
        {sorted.map((d) => (
          <WaterfallPipeline key={d.id} disruption={d} />
        ))}
      </div>
    </div>
  );
}
