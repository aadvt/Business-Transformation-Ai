"use client";

import { useState } from "react";
import { Button, Tag, InlineLoading } from "@carbon/react";
import {
  CheckmarkFilled,
  ChevronDown,
  ChevronUp,
  Time,
  Money,
  Close,
} from "@carbon/icons-react";
import type { Disruption } from "@/lib/types";
import { formatINRFull } from "@/lib/format";
import { formatTimeAgo } from "@/lib/format";

interface ApprovalCardProps {
  disruption: Disruption;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export default function ApprovalCard({ disruption, onApprove, onReject }: ApprovalCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const verifiedCount = disruption.backups.filter((b) => b.verified).length;

  function handleApprove() {
    setDeciding("approve");
    window.setTimeout(() => onApprove(disruption.id), 450);
  }

  function handleReject() {
    setDeciding("reject");
    window.setTimeout(() => onReject(disruption.id), 450);
  }

  return (
    <div className="approval-card">
      <div className="approval-card__bubble">
        <div className="approval-card__header">
          <span className="approval-card__vendor">{disruption.vendorName}</span>
          <Tag type="warm-gray" size="sm">
            {disruption.category}
          </Tag>
        </div>

        <p className="approval-card__issue">{disruption.issue}</p>

        <div className="approval-card__meta">
          <span className="approval-card__meta-item">
            <Time size={16} /> Detected {formatTimeAgo(disruption.detectedAt)}
          </span>
          <span className="approval-card__meta-item approval-card__exposure">
            <Money size={16} /> {formatINRFull(disruption.exposureINR)} exposure
          </span>
        </div>

        <button type="button" className="approval-card__backups-toggle" onClick={() => setExpanded((v) => !v)}>
          <CheckmarkFilled size={16} className="approval-card__check-icon" />
          {verifiedCount} verified backup{verifiedCount === 1 ? "" : "s"} found
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {expanded && (
          <ul className="approval-card__backup-list">
            {disruption.backups.map((b) => (
              <li key={b.id} className="approval-card__backup-item">
                <span className="approval-card__backup-name">{b.name}</span>
                <span className="approval-card__backup-stats">
                  ETA {b.etaDays}d &middot; {b.priceDeltaPct >= 0 ? "+" : ""}
                  {b.priceDeltaPct}% price
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="approval-card__actions">
          <Button
            kind="primary"
            size="sm"
            onClick={handleApprove}
            disabled={deciding !== null}
            renderIcon={deciding === "approve" ? undefined : CheckmarkFilled}
          >
            {deciding === "approve" ? <InlineLoading description="Approving…" /> : "Approve"}
          </Button>
          <Button
            kind="danger--tertiary"
            size="sm"
            onClick={handleReject}
            disabled={deciding !== null}
            renderIcon={deciding === "reject" ? undefined : Close}
          >
            {deciding === "reject" ? <InlineLoading description="Rejecting…" /> : "Reject"}
          </Button>
          <Button kind="ghost" size="sm" onClick={() => setExpanded((v) => !v)} disabled={deciding !== null}>
            See options
          </Button>
        </div>
      </div>
    </div>
  );
}
