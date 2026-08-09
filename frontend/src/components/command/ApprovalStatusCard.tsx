"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Clock3, PhoneOutgoing } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ApprovalDecision } from "@/lib/types";

type Stage = "PENDING" | "APPROVED" | "NEGOTIATING";
const ORDER: Stage[] = ["PENDING", "APPROVED", "NEGOTIATING"];

const DEMO_CONTROLS = process.env.NEXT_PUBLIC_DEMO_CONTROLS === "true";

// The pending-approval placeholder on /command's canvas corner — resolves
// visibly (stamp animation) the instant APPROVAL_DECIDED arrives, whether
// that's from a real WS broadcast or (fixture mode) fixtureBus relaying a
// tap on /phone in the other window. See page.tsx for the subscription.
// Once approved, it grows the "Call vendor" affordance — the entry point to
// D5b's call mode (page.tsx owns the actual POST /calls/start).
export default function ApprovalStatusCard({
  decision,
  vendorName,
  onCallVendor,
  callStarting,
}: {
  decision: ApprovalDecision | null;
  vendorName?: string;
  onCallVendor?: (mode: "LIVE" | "REPLAY") => void;
  callStarting?: boolean;
}) {
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

      {resolved && !rejected && onCallVendor && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.9 }}
          className="mt-3 space-y-1.5"
        >
          <Button
            className="w-full"
            icon={<PhoneOutgoing size={14} />}
            disabled={callStarting}
            onClick={() => onCallVendor("LIVE")}
          >
            {callStarting ? "Starting call…" : `Call ${vendorName ?? "vendor"}`}
          </Button>
          {DEMO_CONTROLS && (
            <button
              type="button"
              disabled={callStarting}
              onClick={() => onCallVendor("REPLAY")}
              className="w-full text-center text-[10.5px] text-ink-faint underline decoration-dotted underline-offset-2 hover:text-ink"
            >
              rehearse with replay instead
            </button>
          )}
        </motion.div>
      )}
    </div>
  );
}
