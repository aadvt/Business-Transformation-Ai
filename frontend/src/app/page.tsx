"use client";

import { motion } from "framer-motion";
import { Activity, AlertTriangle, CheckCircle2, IndianRupee } from "lucide-react";
import { useDashboardSummary, useDisruption, useDisruptions, useVendors } from "@/lib/queries";
import StatTile from "@/components/StatTile";
import ApprovalCard from "@/components/ApprovalCard";
import DisruptionRow from "@/components/DisruptionRow";
import TileGrid from "@/components/ui/TileGrid";
import Skeleton from "@/components/ui/Skeleton";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";

function ApprovalCardLoader({ id }: { id: string }) {
  const { data, isLoading } = useDisruption(id);
  if (isLoading || !data) return <Skeleton className="h-52 max-w-lg" />;
  return <ApprovalCard disruption={data} />;
}

export default function WarRoomPage() {
  const { data: summary, isLoading: summaryLoading } = useDashboardSummary();
  const { data: pending, isLoading: pendingLoading } = useDisruptions("AWAITING_APPROVAL");
  const { data: allDisruptions, isLoading: allLoading } = useDisruptions();
  const { data: vendors, isLoading: vendorsLoading } = useVendors();

  const otherDisruptions = (allDisruptions?.items ?? [])
    .filter((d) => d.stage !== "AWAITING_APPROVAL")
    .sort((a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime());

  return (
    <div>
      <PageHeader
        title="War Room"
        subtitle="Live view of every disruption Sanjeevani is sensing, sourcing around, and settling."
      />

      {summaryLoading || !summary ? (
        <Skeleton className="mb-8 h-28" />
      ) : (
        <TileGrid>
          <StatTile label="Open financial exposure" value={summary.exposure_at_risk_display} icon={IndianRupee} tone="alert" />
          <StatTile label="Disruptions in motion" value={String(summary.active_disruptions)} icon={Activity} />
          <StatTile
            label="Awaiting your approval"
            value={String(pending?.total ?? 0)}
            icon={AlertTriangle}
            tone={(pending?.total ?? 0) > 0 ? "alert" : "default"}
          />
          <StatTile label="Closed today" value={String(summary.disruptions_closed_today)} icon={CheckCircle2} tone="positive" />
        </TileGrid>
      )}

      <section className="mb-10">
        <SectionHeading count={pending?.total}>Pending your approval</SectionHeading>
        {pendingLoading ? (
          <Skeleton className="h-52 max-w-lg" />
        ) : (pending?.items.length ?? 0) === 0 ? (
          <EmptyState>Nothing needs your sign-off right now.</EmptyState>
        ) : (
          <div className="flex flex-col gap-4">
            {pending!.items.map((d) => (
              <ApprovalCardLoader key={d.id} id={d.id} />
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <SectionHeading count={otherDisruptions.length}>Disruption activity</SectionHeading>
        {allLoading ? (
          <Skeleton className="h-32" />
        ) : otherDisruptions.length === 0 ? (
          <EmptyState>No other activity yet.</EmptyState>
        ) : (
          <div>
            {otherDisruptions.map((d) => (
              <DisruptionRow key={d.id} disruption={d} />
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <SectionHeading count={vendors?.total}>Vendor directory</SectionHeading>
        {vendorsLoading ? (
          <Skeleton className="h-40" />
        ) : (
          <div className="glass-panel overflow-hidden rounded-2xl">
            <div className="grid grid-cols-[1.6fr_1fr_0.9fr_1.1fr] gap-4 border-b border-white/[0.07] px-5 py-3 text-[0.625rem] font-semibold tracking-[0.1em] text-ink-faint uppercase">
              <span>Vendor</span>
              <span>Category</span>
              <span>City</span>
              <span>Reliability</span>
            </div>
            {(vendors?.items ?? []).map((v, i) => (
              <motion.div
                key={v.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.04 }}
                className="grid grid-cols-[1.6fr_1fr_0.9fr_1.1fr] items-center gap-4 border-b border-white/[0.04] px-5 py-3 text-[0.8125rem] transition-colors last:border-b-0 hover:bg-white/[0.035]"
              >
                <span className="font-medium text-ink">{v.name}</span>
                <span className="text-ink-muted">{v.category}</span>
                <span className="text-ink-muted">{v.city}</span>
                <span className="flex items-center gap-2.5">
                  <span className="h-1 w-16 overflow-hidden rounded-full bg-white/10">
                    <motion.span
                      className="block h-full rounded-full bg-gradient-to-r from-accent to-positive"
                      initial={{ width: 0 }}
                      animate={{ width: `${v.reliability_score_0_100}%` }}
                      transition={{ delay: 0.15 + i * 0.05, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
                    />
                  </span>
                  <span className="tabular-money text-ink-muted">{v.reliability_score_0_100}%</span>
                </span>
              </motion.div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
