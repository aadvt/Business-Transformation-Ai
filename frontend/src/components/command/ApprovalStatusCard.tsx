"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Clock3 } from "lucide-react";
import type { ApprovalDecision } from "@/lib/types";

type Stage = "PENDING" | "APPROVED" | "NEGOTIATING";
const ORDER: Stage[] = ["PENDING", "APPROVED", "NEGOTIATING"];

// The pending-approval placeholder on /command's canvas corner — resolves
// visibly (stamp animation) the instant APPROVAL_DECIDED arrives, whether
// that's from a real WS broadcast or (fixture mode) fixtureBus relaying a
// tap on /phone in the other window. See page.tsx for the subscription.
export default function ApprovalStatusCard({ decision }: { decision: ApprovalDecision | null }) {
  const [stage, setStage] = useState<Stage>("PENDING");

  useEffect(() => {
    if (decision !== "APPROVE") return;
    setStage("APPROVED");
    const timeout = setTimeout(() => setStage("NEGOTIATING"), 1100);
    return () => clearTimeout(timeout);
  }, [decision]);

  const resolved = decision !== null;
  const rejected = decision === "REJECT" || decision === "REQUEST_OPTIONS";

  return (
    <div className="elevated w-72 rounded-lg p-4">
      <p className="eyebrow mb-2">Approval</p>
      <AnimatePresence mode="wait">
        {!resolved ? (
          <motion.div
            key="pending"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex items-center gap-2 text-[13px] text-ink-muted"
          >
            <Clock3 size={14} /> Awaiting the owner&apos;s decision on WhatsApp…
          </motion.div>
        ) : rejected ? (
          <motion.div
            key="rejected"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex items-center gap-2 text-[13px] font-medium text-ink-muted"
          >
            Owner requested other options via WhatsApp.
          </motion.div>
        ) : (
          <motion.div
            key="decided"
            initial={{ opacity: 0, scale: 0.85 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ type: "spring", stiffness: 300, damping: 20 }}
            className="flex items-center gap-2 text-[13px] font-medium text-success"
          >
            <motion.span
              initial={{ rotate: -25, scale: 0 }}
              animate={{ rotate: 0, scale: 1 }}
              transition={{ delay: 0.1, type: "spring", stiffness: 400, damping: 14 }}
            >
              <CheckCircle2 size={16} />
            </motion.span>
            {stage === "APPROVED" ? "Approved by owner via WhatsApp" : "Negotiating with backup vendor…"}
          </motion.div>
        )}
      </AnimatePresence>

      {resolved && !rejected && (
        <div className="mt-3 flex items-center gap-1.5">
          {ORDER.map((s, i) => (
            <span key={s} className={`h-1 flex-1 rounded-sm ${ORDER.indexOf(stage) >= i ? "bg-success" : "bg-surface-3"}`} />
          ))}
        </div>
      )}
    </div>
  );
}
