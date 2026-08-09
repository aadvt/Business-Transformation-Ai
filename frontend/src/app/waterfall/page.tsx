"use client";

import { useAgentsStatus, useDisruptions } from "@/lib/queries";
import AgentStatusStrip from "@/components/AgentStatusStrip";
import WaterfallPipeline from "@/components/WaterfallPipeline";
import Skeleton from "@/components/ui/skeleton";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";
import type { DisruptionStage } from "@/lib/types";

const STAGE_RANK: Record<DisruptionStage, number> = {
  AWAITING_APPROVAL: 0,
  NEGOTIATING: 1,
  NEGOTIATED: 1,
  DETECTED: 2,
  DIAGNOSED: 2,
  SOURCING: 2,
  APPROVED: 2,
  SETTLEMENT_PENDING: 3,
  SETTLED: 4,
  CLOSED: 4,
  REJECTED: 5,
  FAILED: 5,
};

export default function WaterfallPage() {
  const { data: agentsResponse, isLoading: agentsLoading } = useAgentsStatus();
  const { data: disruptionsResponse, isLoading: disruptionsLoading } = useDisruptions();

  const sorted = [...(disruptionsResponse?.items ?? [])].sort(
    (a, b) => STAGE_RANK[a.stage] - STAGE_RANK[b.stage] || new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
  );

  return (
    <div>
      <PageHeader
        title="Pipeline"
        subtitle="Per-disruption progress through all six stages, and the live status of the agent that owns each one."
      />

      <section className="mb-6">
        <SectionHeading count={agentsResponse?.agents.length}>Agent mesh</SectionHeading>
        {agentsLoading || !agentsResponse ? (
          <Skeleton className="h-20" />
        ) : (
          <AgentStatusStrip agents={agentsResponse.agents} />
        )}
      </section>

      <section>
        <SectionHeading count={sorted.length}>Disruptions in flight</SectionHeading>
        {disruptionsLoading ? (
          <Skeleton className="h-44" />
        ) : sorted.length === 0 ? (
          <EmptyState>Nothing in the pipeline right now.</EmptyState>
        ) : (
          <div className="flex flex-col gap-3">
            {sorted.map((d) => (
              <WaterfallPipeline key={d.id} disruption={d} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
