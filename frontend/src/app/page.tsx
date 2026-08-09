"use client";

import { AlertTriangle, Boxes, CheckCircle2, IndianRupee } from "lucide-react";
import { useAgentsStatus, useDashboardSummary, useDisruption, useDisruptions, useVendors } from "@/lib/queries";
import StatTile from "@/components/StatTile";
import ApprovalCard from "@/components/ApprovalCard";
import DisruptionRow from "@/components/DisruptionRow";
import PipelineBoard from "@/components/PipelineBoard";
import TileGrid from "@/components/ui/TileGrid";
import Skeleton from "@/components/ui/Skeleton";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";

function ApprovalCardLoader({ id }: { id: string }) {
  const { data, isLoading } = useDisruption(id);
  if (isLoading || !data) return <Skeleton className="h-40 max-w-xl" />;
  return <ApprovalCard disruption={data} />;
}

export default function WarRoomPage() {
  const { data: summary, isLoading: summaryLoading } = useDashboardSummary();
  const { data: pending, isLoading: pendingLoading } = useDisruptions("AWAITING_APPROVAL");
  const { data: allDisruptions, isLoading: allLoading } = useDisruptions();
  const { data: agentsResponse } = useAgentsStatus();
  const { data: vendors, isLoading: vendorsLoading } = useVendors();

  const disruptions = allDisruptions?.items ?? [];
  const recent = [...disruptions].sort(
    (a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime()
  );

  return (
    <div>
      <PageHeader
        title="War Room"
        subtitle="Every disruption Sanjeevani is sensing, sourcing around, and settling — end to end."
      />

      {summaryLoading || !summary ? (
        <Skeleton className="mb-6 h-[86px]" />
      ) : (
        <TileGrid minWidth={180}>
          <StatTile label="Exposure at risk" value={summary.exposure_at_risk_display} icon={IndianRupee} tone="alert" />
          <StatTile label="Active disruptions" value={String(summary.active_disruptions)} icon={Boxes} />
          <StatTile
            label="Awaiting approval"
            value={String(pending?.total ?? 0)}
            icon={AlertTriangle}
            tone={(pending?.total ?? 0) > 0 ? "alert" : "default"}
          />
          <StatTile
            label="Mitigated"
            value={summary.exposure_mitigated_display}
            icon={CheckCircle2}
            tone="positive"
          />
          <StatTile label="Closed today" value={String(summary.disruptions_closed_today)} icon={CheckCircle2} />
        </TileGrid>
      )}

      {allLoading || !agentsResponse ? (
        <Skeleton className="mb-6 h-56" />
      ) : (
        <PipelineBoard disruptions={disruptions} agents={agentsResponse.agents} />
      )}

      <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section>
          <SectionHeading count={pending?.total}>Awaiting your approval</SectionHeading>
          {pendingLoading ? (
            <Skeleton className="h-40" />
          ) : (pending?.items.length ?? 0) === 0 ? (
            <EmptyState>Nothing needs your sign-off right now.</EmptyState>
          ) : (
            <div className="flex flex-col gap-3">
              {pending!.items.map((d) => (
                <ApprovalCardLoader key={d.id} id={d.id} />
              ))}
            </div>
          )}
        </section>

        <section>
          <SectionHeading count={recent.length}>Recent activity</SectionHeading>
          {allLoading ? (
            <Skeleton className="h-40" />
          ) : recent.length === 0 ? (
            <EmptyState>No activity yet.</EmptyState>
          ) : (
            <div>
              {recent.map((d) => (
                <DisruptionRow key={d.id} disruption={d} />
              ))}
            </div>
          )}
        </section>
      </div>

      <section>
        <SectionHeading count={vendors?.total}>Vendor directory</SectionHeading>
        {vendorsLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="panel-flush">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-line">
                  <th className="eyebrow px-4 py-2 font-semibold">Vendor</th>
                  <th className="eyebrow px-4 py-2 font-semibold">Category</th>
                  <th className="eyebrow px-4 py-2 font-semibold">Location</th>
                  <th className="eyebrow px-4 py-2 text-right font-semibold">On-time</th>
                  <th className="eyebrow px-4 py-2 text-right font-semibold">Outstanding</th>
                  <th className="eyebrow px-4 py-2 font-semibold">Reliability</th>
                </tr>
              </thead>
              <tbody>
                {(vendors?.items ?? []).map((v) => (
                  <tr key={v.id} className="row-hover border-b border-line last:border-b-0">
                    <td className="px-4 py-2 text-[13px] font-medium text-ink">{v.name}</td>
                    <td className="px-4 py-2 text-[13px] text-ink-muted">{v.category}</td>
                    <td className="px-4 py-2 text-[13px] text-ink-muted">
                      {v.city}, {v.state}
                    </td>
                    <td className="numeric px-4 py-2 text-right text-[13px] text-ink-muted">
                      {Math.round(v.on_time_rate * 100)}%
                    </td>
                    <td className="numeric px-4 py-2 text-right text-[13px] text-ink">{v.dues_display}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <span className="h-1 w-14 overflow-hidden rounded-sm bg-surface-3">
                          <span
                            className={
                              v.reliability_score_0_100 >= 80
                                ? "block h-full bg-success"
                                : v.reliability_score_0_100 >= 60
                                  ? "block h-full bg-warning"
                                  : "block h-full bg-critical"
                            }
                            style={{ width: `${v.reliability_score_0_100}%` }}
                          />
                        </span>
                        <span className="numeric text-xs text-ink-muted">{v.reliability_score_0_100}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
