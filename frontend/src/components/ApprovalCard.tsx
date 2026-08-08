"use client";

import { useState } from "react";
import { Check, CheckCircle2, ChevronDown, ChevronUp, Clock, IndianRupee, X } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import type { Disruption } from "@/lib/types";
import { formatTimeAgo } from "@/lib/format";
import { useDecideApproval } from "@/lib/queries";
import Button from "./ui/Button";
import Badge from "./ui/Badge";
import Spinner from "./ui/Spinner";

export default function ApprovalCard({ disruption }: { disruption: Disruption }) {
  const [expanded, setExpanded] = useState(false);
  const decide = useDecideApproval();

  const approvalId = disruption.approval?.id;
  const verifiedCount = disruption.candidates.filter((c) => c.verification.status === "VERIFIED").length;
  const deciding = decide.isPending ? decide.variables?.decision : undefined;

  function handleDecision(decision: "APPROVE" | "REJECT") {
    if (!approvalId) return;
    decide.mutate({ approvalId, decision });
  }

  return (
    <motion.div
      className="glass-panel rounded-2xl border-l-2 border-l-accent p-5"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[0.95rem] font-semibold text-ink">{disruption.vendor.name}</span>
        <Badge tone="idle">{disruption.type.replace(/_/g, " ")}</Badge>
      </div>

      <p className="mb-3 text-sm leading-relaxed text-ink-muted">{disruption.headline}</p>

      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-1">
          <Clock size={14} /> Detected {formatTimeAgo(disruption.detected_at)}
        </span>
        <span className="inline-flex items-center gap-1 font-semibold text-accent-strong">
          <IndianRupee size={14} /> <span className="tabular-money">{disruption.exposure.total_display}</span> exposure
        </span>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="mb-2 inline-flex cursor-pointer items-center gap-1.5 border-none bg-transparent p-0 text-[0.8125rem] font-semibold text-positive"
      >
        <CheckCircle2 size={16} />
        {verifiedCount} verified candidate{verifiedCount === 1 ? "" : "s"} found
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.ul
            className="mb-3 flex flex-col gap-1.5 overflow-hidden"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
          >
            {disruption.candidates.map((c) => (
              <li
                key={c.vendor_id}
                className="glass-subtle rounded-xl px-2.5 py-1.5 text-[0.8125rem] flex items-center justify-between gap-2"
              >
                <span className="font-medium text-ink">{c.name}</span>
                <span className="text-xs whitespace-nowrap text-ink-muted">
                  ETA {c.quoted_lead_time_days}d &middot; match {(c.match_score * 100).toFixed(0)}%
                </span>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>

      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => handleDecision("APPROVE")}
          disabled={decide.isPending || !approvalId}
          icon={deciding === "APPROVE" ? undefined : <Check size={14} />}
        >
          {deciding === "APPROVE" ? <Spinner size={14} label="Approving…" /> : "Approve"}
        </Button>
        <Button
          variant="danger"
          size="sm"
          onClick={() => handleDecision("REJECT")}
          disabled={decide.isPending || !approvalId}
          icon={deciding === "REJECT" ? undefined : <X size={14} />}
        >
          {deciding === "REJECT" ? <Spinner size={14} label="Rejecting…" /> : "Reject"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setExpanded((v) => !v)} disabled={decide.isPending}>
          See options
        </Button>
      </div>
    </motion.div>
  );
}
