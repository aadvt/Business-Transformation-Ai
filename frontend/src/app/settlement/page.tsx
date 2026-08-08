"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Layers, Wallet } from "lucide-react";
import { useConfirmSettlementBatch, useExecuteSettlementBatch, useSettlementBatches } from "@/lib/queries";
import { formatPaiseFull } from "@/lib/format";
import StatTile from "@/components/StatTile";
import TileGrid from "@/components/ui/TileGrid";
import Skeleton from "@/components/ui/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Toast from "@/components/ui/Toast";
import PageHeader, { EmptyState, SectionHeading } from "@/components/PageHeader";
import type { SettlementBatch, TransactionAgentHandoff } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  PENDING: "Pending",
  EXECUTING: "Executing",
  CONFIRMED: "Confirmed",
};

const STATUS_TONE: Record<string, "idle" | "progress" | "positive" | "accent"> = {
  PENDING: "idle",
  EXECUTING: "progress",
  CONFIRMED: "positive",
};

interface BatchCardProps {
  batch: SettlementBatch;
  index: number;
  onConfirmed: (batch: SettlementBatch, handoff?: TransactionAgentHandoff | null) => void;
}

function BatchCard({ batch, index, onConfirmed }: BatchCardProps) {
  const confirm = useConfirmSettlementBatch();
  const execute = useExecuteSettlementBatch();

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.07, type: "spring", stiffness: 300, damping: 30 }}
      className="glass-panel mb-5 overflow-hidden rounded-2xl"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent/12 ring-1 ring-accent/20">
            <Layers size={16} className="text-accent-strong" />
          </span>
          <div>
            <p className="text-sm font-semibold text-ink">Batch {batch.month}</p>
            <p className="tabular-money text-lg leading-tight font-semibold text-accent-strong">{batch.total_display}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge tone={STATUS_TONE[batch.status] ?? "idle"}>{STATUS_LABEL[batch.status] ?? batch.status}</Badge>
          {batch.status === "PENDING" && (
            <Button
              size="sm"
              onClick={() => confirm.mutate({ batchId: batch.id }, { onSuccess: () => onConfirmed(batch) })}
              disabled={confirm.isPending}
            >
              {confirm.isPending ? "Confirming…" : "Confirm batch"}
            </Button>
          )}
          {batch.status === "CONFIRMED" && (
            <Button
              size="sm"
              icon={<Wallet size={14} />}
              onClick={() =>
                execute.mutate({ batchId: batch.id }, { onSuccess: (data) => onConfirmed(batch, data.transaction_agent) })
              }
              disabled={execute.isPending}
            >
              {execute.isPending ? "Executing…" : "Execute payout"}
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-[1.8fr_1fr_1fr_1fr] gap-3 border-b border-white/[0.05] px-5 py-2.5 text-[0.625rem] font-semibold tracking-[0.1em] text-ink-faint uppercase">
        <span>Vendor</span>
        <span>Invoice</span>
        <span>Due date</span>
        <span className="text-right">Amount</span>
      </div>
      {batch.lines.map((line) => (
        <div
          key={line.invoice_id}
          className="grid grid-cols-[1.8fr_1fr_1fr_1fr] items-center gap-3 border-b border-white/[0.04] px-5 py-3 text-[0.8125rem] transition-colors last:border-b-0 hover:bg-white/[0.035]"
        >
          <span className="font-medium text-ink">{line.vendor.name}</span>
          <span className="text-ink-muted">{line.invoice_id}</span>
          <span className="text-ink-muted">{line.due_date}</span>
          <span className="tabular-money text-right font-semibold text-ink">{line.amount_display}</span>
        </div>
      ))}
    </motion.div>
  );
}

export default function SettlementPage() {
  const { data, isLoading } = useSettlementBatches();
  const [confirmation, setConfirmation] = useState<{ month: string; amount: string; threadId?: string } | null>(null);

  const batches = data?.items ?? [];
  const outstandingPaise = batches.filter((b) => b.status !== "CONFIRMED").reduce((sum, b) => sum + b.total_paise, 0);
  const confirmedCount = batches.filter((b) => b.status === "CONFIRMED").length;

  return (
    <div>
      <PageHeader
        title="Settlement"
        subtitle="One consolidated batch instead of dozens of individual payouts. Confirm a batch, then hand it to the transaction agent for UPI payout execution."
      />

      {isLoading ? (
        <Skeleton className="mb-8 h-28" />
      ) : (
        <TileGrid>
          <StatTile label="Total outstanding" value={formatPaiseFull(outstandingPaise)} icon={Wallet} tone="alert" />
          <StatTile label="Batches" value={String(batches.length)} icon={Layers} />
          <StatTile label="Confirmed this cycle" value={String(confirmedCount)} icon={CheckCircle2} tone="positive" />
        </TileGrid>
      )}

      {confirmation && (
        <Toast
          title="Settlement staged"
          subtitle={
            confirmation.threadId
              ? `Batch ${confirmation.month} · ${confirmation.amount} — staged with the transaction agent (thread ${confirmation.threadId.slice(0, 8)}…), pending its own approval.`
              : `Batch ${confirmation.month} · ${confirmation.amount} — confirmed. Execute to hand it to the transaction agent.`
          }
          onClose={() => setConfirmation(null)}
        />
      )}

      <section>
        <SectionHeading count={batches.length}>Payout batches</SectionHeading>
        {isLoading ? (
          <Skeleton className="h-52" />
        ) : batches.length === 0 ? (
          <EmptyState>No settlement batches yet.</EmptyState>
        ) : (
          batches.map((batch, i) => (
            <BatchCard
              key={batch.id}
              batch={batch}
              index={i}
              onConfirmed={(b, handoff) =>
                setConfirmation({ month: b.month, amount: b.total_display, threadId: handoff?.thread_id })
              }
            />
          ))
        )}
      </section>
    </div>
  );
}
