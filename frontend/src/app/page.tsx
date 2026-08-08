"use client";

import { Money, WarningAltFilled, FlowData, CheckmarkOutline } from "@carbon/icons-react";
import { useSanjeevani } from "@/lib/store";
import { formatINR } from "@/lib/format";
import StatTile from "@/components/StatTile";
import ApprovalCard from "@/components/ApprovalCard";
import DisruptionRow from "@/components/DisruptionRow";
import { VENDORS } from "@/lib/mockData";

export default function WarRoomPage() {
  const { disruptions, approve, reject, totalOpenExposureINR, pendingApprovalsCount } = useSanjeevani();

  const awaitingApproval = disruptions.filter((d) => d.status === "awaiting_approval");
  const otherDisruptions = disruptions
    .filter((d) => d.status !== "awaiting_approval")
    .sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime());

  const activeCount = disruptions.filter((d) => d.status === "active" || d.status === "negotiating").length;
  const settledTodayCount = disruptions.filter((d) => d.status === "settled").length;

  return (
    <div>
      <h1 className="sanjeevani-page-title">War Room</h1>
      <p className="sanjeevani-page-subtitle">Live view of every disruption Sanjeevani is sensing, sourcing around, and settling.</p>

      <div className="stat-grid">
        <StatTile label="Open financial exposure" value={formatINR(totalOpenExposureINR)} icon={Money} tone="alert" />
        <StatTile label="Disruptions in motion" value={String(activeCount)} icon={FlowData} />
        <StatTile label="Awaiting your approval" value={String(pendingApprovalsCount)} icon={WarningAltFilled} tone={pendingApprovalsCount > 0 ? "alert" : "default"} />
        <StatTile label="Settled" value={String(settledTodayCount)} icon={CheckmarkOutline} tone="positive" />
      </div>

      <section className="sanjeevani-section">
        <div className="sanjeevani-section__heading">
          <h2 className="sanjeevani-section__title">Pending your approval</h2>
        </div>
        {awaitingApproval.length === 0 ? (
          <div className="sanjeevani-section__empty">Nothing needs your sign-off right now.</div>
        ) : (
          <div className="approval-card-grid">
            {awaitingApproval.map((d) => (
              <ApprovalCard key={d.id} disruption={d} onApprove={approve} onReject={reject} />
            ))}
          </div>
        )}
      </section>

      <section className="sanjeevani-section">
        <div className="sanjeevani-section__heading">
          <h2 className="sanjeevani-section__title">Disruption activity</h2>
        </div>
        {otherDisruptions.length === 0 ? (
          <div className="sanjeevani-section__empty">No other activity yet.</div>
        ) : (
          <div>
            {otherDisruptions.map((d) => (
              <DisruptionRow key={d.id} disruption={d} />
            ))}
          </div>
        )}
      </section>

      <section className="sanjeevani-section">
        <div className="sanjeevani-section__heading">
          <h2 className="sanjeevani-section__title">Vendor directory</h2>
        </div>
        <div className="vendor-table">
          <div className="vendor-table__row vendor-table__row--head">
            <span>Vendor</span>
            <span>Category</span>
            <span>City</span>
            <span>Reliability</span>
          </div>
          {VENDORS.map((v) => (
            <div className="vendor-table__row" key={v.id}>
              <span className="vendor-table__name">{v.name}</span>
              <span>{v.category}</span>
              <span>{v.city}</span>
              <span className="vendor-table__reliability">
                <span className="vendor-table__bar">
                  <span className="vendor-table__bar-fill" style={{ width: `${v.reliabilityPct}%` }} />
                </span>
                {v.reliabilityPct}%
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
