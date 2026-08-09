"use client";

import { useAgentsStatus, useDisruptions } from "@/lib/queries";
import AgentStatusStrip from "@/components/AgentStatusStrip";
import UpdatesBoard from "@/components/UpdatesBoard";
import Skeleton from "@/components/ui/skeleton";
import PageHeader, { SectionHeading } from "@/components/PageHeader";

export default function WaterfallPage() {
  const { data: agentsResponse, isLoading: agentsLoading } = useAgentsStatus();
  const { data: disruptionsResponse, isLoading: disruptionsLoading } = useDisruptions();

  const disruptions = disruptionsResponse?.items ?? [];

  return (
    <div>
      <PageHeader
        title="Updates"
        subtitle="Everything in flight, held in the lane for the stage it is actually sitting in — so what is stuck, and where, is a position on the board rather than something you read off every row."
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
        <SectionHeading count={disruptionsLoading ? undefined : disruptions.length}>
          Disruptions in flight
        </SectionHeading>
        <UpdatesBoard disruptions={disruptions} isLoading={disruptionsLoading} />
      </section>
    </div>
  );
}
