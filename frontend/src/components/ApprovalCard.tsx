"use client";

import { useState } from "react";
import { Check, CheckCircle2, ChevronDown, ChevronUp, Clock, IndianRupee, X } from "lucide-react";
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

  const approvalId = disruption.approval?.id;
  const verifiedCount = disruption.candidates.filter((c) => c.verification.status === "VERIFIED").length;
  const deciding = decide.isPending ? decide.variables?.decision : undefined;

  function handleDecision(decision: "APPROVE" | "REJECT") {
    if (!approvalId) return;
    decide.mutate({ approvalId, decision });
    if (decision === "REJECT") setConfirmingReject(false);
  }

  return (
    <Card className="border-l-2 border-l-accent">
      <CardContent className="p-4">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-[0.95rem] font-semibold text-ink">{disruption.vendor.name}</span>
          <Badge tone="idle" dot={false}>
            {disruption.type.replace(/_/g, " ")}
          </Badge>
        </div>

        <p className="mb-3 text-sm leading-relaxed text-ink-muted">{disruption.headline}</p>

        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
          <span className="inline-flex items-center gap-1">
            <Clock size={14} /> Detected {formatTimeAgo(disruption.detected_at)}
          </span>
          <span className="inline-flex items-center gap-1 font-semibold text-accent">
            <IndianRupee size={14} /> <span className="numeric">{disruption.exposure.total_display}</span> exposure
          </span>
        </div>

        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mb-2 inline-flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-[0.8125rem] font-semibold text-success"
        >
          <CheckCircle2 size={16} />
          {verifiedCount} verified candidate{verifiedCount === 1 ? "" : "s"} found
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>

        {expanded && (
          <ul className="mb-3 flex flex-col gap-1.5">
            {disruption.candidates.map((c) => (
              <li
                key={c.vendor_id}
                className="flex items-center justify-between gap-2 rounded-md bg-surface-2 px-2.5 py-1.5 text-xs"
              >
                <span className="font-medium text-ink">{c.name}</span>
                <span className="numeric whitespace-nowrap text-ink-muted">
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
