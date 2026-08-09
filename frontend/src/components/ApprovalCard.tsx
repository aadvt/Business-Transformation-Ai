"use client";

import { useId, useState } from "react";
import { Check, CheckCircle2, ChevronDown, ChevronUp, Clock, X } from "lucide-react";
import type { Disruption } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import { useDecideApproval } from "@/lib/queries";
import { Button } from "./ui/button";
import Badge from "./ui/badge";
import Spinner from "./ui/Spinner";
import { Card, CardContent } from "./ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";

export default function ApprovalCard({ disruption }: { disruption: Disruption }) {
  const [expanded, setExpanded] = useState(false);
  const [confirmingReject, setConfirmingReject] = useState(false);
  const decide = useDecideApproval();
  const candidatesId = useId();

  const approvalId = disruption.approval?.id;
  const verifiedCount = disruption.candidates.filter((c) => c.verification.status === "VERIFIED").length;
  const deciding = decide.isPending ? decide.variables?.decision : undefined;

  function handleDecision(decision: "APPROVE" | "REJECT") {
    if (!approvalId) return;
    decide.mutate({ approvalId, decision });
    if (decision === "REJECT") setConfirmingReject(false);
  }

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-2 flex items-start justify-between gap-2">
          <h3 className="min-w-0 truncate text-[15px] leading-tight font-semibold text-ink">
            {disruption.vendor.name}
          </h3>
          <Badge tone="idle" dot={false} className="shrink-0">
            {disruption.type.replace(/_/g, " ")}
          </Badge>
        </div>

        <p className="mb-3 text-[13px] leading-relaxed text-ink-muted">{disruption.headline}</p>

        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
          <span className="inline-flex items-center gap-1 text-ink-faint">
            <Clock size={13} /> Detected {formatTimeAgo(disruption.detected_at)}
          </span>
          <span className="inline-flex items-baseline gap-1 text-ink-muted">
            <span className="numeric font-semibold text-accent" data-numeric>
              {disruption.exposure.total_display}
            </span>
            exposure
          </span>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={candidatesId}
          className="-mx-1.5 mb-2 inline-flex cursor-pointer items-center gap-1.5 rounded-sm border-none bg-transparent px-1.5 py-1 text-[13px] font-semibold text-success transition-colors duration-150 hover:bg-success-dim"
        >
          <CheckCircle2 size={15} />
          <span className="numeric" data-numeric>
            {verifiedCount}
          </span>
          verified candidate{verifiedCount === 1 ? "" : "s"} found
          {expanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>

        {expanded && (
          <ul id={candidatesId} className="mb-3 flex flex-col gap-1">
            {disruption.candidates.map((c) => (
              <li
                key={c.vendor_id}
                className="flex items-center justify-between gap-2 rounded-md bg-surface-2 px-2.5 py-1.5 text-xs"
              >
                <span className="min-w-0 truncate font-medium text-ink">{c.name}</span>
                <span className="numeric shrink-0 whitespace-nowrap text-ink-muted" data-numeric>
                  ETA {c.quoted_lead_time_days}d &middot; match {(c.match_score * 100).toFixed(0)}%
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() => handleDecision("APPROVE")}
            disabled={decide.isPending || !approvalId}
            icon={deciding === "APPROVE" ? undefined : <Check size={14} />}
          >
            {deciding === "APPROVE" ? <Spinner size={14} label="Approving…" /> : "Approve"}
          </Button>
          <Dialog open={confirmingReject} onOpenChange={setConfirmingReject}>
            <DialogTrigger
              render={
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={decide.isPending || !approvalId}
                  icon={deciding === "REJECT" ? undefined : <X size={14} />}
                />
              }
            >
              {deciding === "REJECT" ? <Spinner size={14} label="Rejecting…" /> : "Reject"}
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Reject this recommendation?</DialogTitle>
                <DialogDescription>
                  {disruption.vendor.name} · {disruption.exposure.total_display} exposure will stay unresolved and
                  routed back for a fresh sourcing pass.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose render={<Button variant="secondary" size="sm" />}>Cancel</DialogClose>
                <Button variant="destructive" size="sm" onClick={() => handleDecision("REJECT")}>
                  Reject
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button variant="ghost" size="sm" onClick={() => setExpanded((v) => !v)} disabled={decide.isPending}>
            See options
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
