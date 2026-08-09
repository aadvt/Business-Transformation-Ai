"use client";

import { useState } from "react";
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
  onConfirmed: (batch: SettlementBatch, handoff?: TransactionAgentHandoff | null) => void;
}

function BatchCard({ batch, onConfirmed }: BatchCardProps) {
  const confirm = useConfirmSettlementBatch();
  const execute = useExecuteSettlementBatch();

  return (
    <div className="panel-flush mb-3">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="eyebrow">Batch</span>
          <span className="numeric text-[13px] font-medium text-ink">{batch.month}</span>
          <span className="numeric text-[15px] font-medium text-accent">{batch.total_display}</span>
          <span className="text-[11px] text-ink-faint">
            {batch.lines.length} line{batch.lines.length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="flex items-center gap-2.5">
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
              icon={<Wallet size={13} />}
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

      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-line">
            <th className="eyebrow px-4 py-2 font-semibold">Vendor</th>
            <th className="eyebrow px-4 py-2 font-semibold">Invoice</th>
            <th className="eyebrow px-4 py-2 font-semibold">Due</th>
            <th className="eyebrow px-4 py-2 text-right font-semibold">Amount</th>
          </tr>
        </thead>
        <tbody>
          {batch.lines.map((line) => (
            <tr key={line.invoice_id} className="row-hover border-b border-line last:border-b-0">
              <td className="px-4 py-2 text-[13px] font-medium text-ink">{line.vendor.name}</td>
              <td className="numeric px-4 py-2 text-xs text-ink-muted">{line.invoice_id}</td>
              <td className="numeric px-4 py-2 text-xs text-ink-muted">{line.due_date}</td>
              <td className="numeric px-4 py-2 text-right text-[13px] text-ink">{line.amount_display}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SettlementPage() {
  const { data, isLoading } = useSettlementBatches();
  const [confirmation, setConfirmation] = useState<{ month: string; amount: string; threadId?: string } | null>(null);

  const batches = data?.items ?? [];
  const outstandingPaise = batches.filter((b) => b.status !== "CONFIRMED").reduce((sum, b) => sum + b.total_paise, 0);
  const confirmedCount = batches.filter((b) => b.status === "CONFIRMED").length;
  const lineCount = batches.reduce((sum, b) => sum + b.lines.length, 0);

  return (
    <div>
      <PageHeader
        title="Settlement"
        subtitle="One consolidated batch instead of dozens of individual payouts. Confirm a batch, then hand it to the transaction agent for execution."
      />

      {isLoading ? (
        <Skeleton className="mb-6 h-[86px]" />
      ) : (
        <TileGrid minWidth={180}>
          <StatTile label="Outstanding" value={formatPaiseFull(outstandingPaise)} icon={Wallet} tone="alert" />
          <StatTile label="Batches" value={String(batches.length)} icon={Layers} />
          <StatTile label="Invoice lines" value={String(lineCount)} icon={Layers} />
          <StatTile label="Confirmed" value={String(confirmedCount)} icon={CheckCircle2} tone="positive" />
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
          <Skeleton className="h-44" />
        ) : batches.length === 0 ? (
          <EmptyState>No settlement batches yet.</EmptyState>
        ) : (
          batches.map((batch) => (
            <BatchCard
              key={batch.id}
              batch={batch}
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
