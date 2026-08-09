"use client";

import { useState } from "react";
import { CheckCircle2, Layers, Wallet } from "lucide-react";
import { toast } from "sonner";
import { useConfirmSettlementBatch, useExecuteSettlementBatch, useSettlementBatches } from "@/lib/queries";
import { formatPaiseFull } from "@/lib/format";
import StatTile from "@/components/StatTile";
import TileGrid from "@/components/ui/TileGrid";
import Skeleton from "@/components/ui/skeleton";
import Badge from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
  const [confirmingExecute, setConfirmingExecute] = useState(false);

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
            <Dialog open={confirmingExecute} onOpenChange={setConfirmingExecute}>
              <DialogTrigger render={<Button size="sm" icon={<Wallet size={13} />} disabled={execute.isPending} />}>
                {execute.isPending ? "Executing…" : "Execute payout"}
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Execute payout for batch {batch.month}?</DialogTitle>
                  <DialogDescription>
                    {batch.total_display} across {batch.lines.length} invoice{batch.lines.length === 1 ? "" : "s"} will
                    be handed to the transaction agent for execution. This cannot be undone from here.
                  </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose render={<Button variant="secondary" size="sm" />}>Cancel</DialogClose>
                  <Button
                    size="sm"
                    icon={<Wallet size={13} />}
                    onClick={() => {
                      execute.mutate(
                        { batchId: batch.id },
                        {
                          onSuccess: (data) => {
                            onConfirmed(batch, data.transaction_agent);
                            setConfirmingExecute(false);
                          },
                        }
                      );
                    }}
                    disabled={execute.isPending}
                  >
                    {execute.isPending ? "Executing…" : "Confirm & execute"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Vendor</TableHead>
            <TableHead>Invoice</TableHead>
            <TableHead>Due</TableHead>
            <TableHead className="text-right">Amount</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {batch.lines.map((line) => (
            <TableRow key={line.invoice_id}>
              <TableCell className="font-medium">{line.vendor.name}</TableCell>
              <TableCell className="numeric text-xs text-ink-muted">{line.invoice_id}</TableCell>
              <TableCell className="numeric text-xs text-ink-muted">{line.due_date}</TableCell>
              <TableCell className="numeric text-right">{line.amount_display}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function SettlementPage() {
  const { data, isLoading } = useSettlementBatches();

  const batches = data?.items ?? [];
  const outstandingPaise = batches.filter((b) => b.status !== "CONFIRMED").reduce((sum, b) => sum + b.total_paise, 0);
  const confirmedCount = batches.filter((b) => b.status === "CONFIRMED").length;
  const lineCount = batches.reduce((sum, b) => sum + b.lines.length, 0);

  function handleConfirmed(batch: SettlementBatch, handoff?: TransactionAgentHandoff | null) {
    if (handoff?.thread_id) {
      toast.success("Settlement staged", {
        description: `Batch ${batch.month} · ${batch.total_display} — staged with the transaction agent (thread ${handoff.thread_id.slice(0, 8)}…), pending its own approval.`,
      });
    } else {
      toast.success("Batch confirmed", {
        description: `Batch ${batch.month} · ${batch.total_display} — confirmed. Execute to hand it to the transaction agent.`,
      });
    }
  }

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

      <section>
        <SectionHeading count={batches.length}>Payout batches</SectionHeading>
        {isLoading ? (
          <Skeleton className="h-44" />
        ) : batches.length === 0 ? (
          <EmptyState>No settlement batches yet.</EmptyState>
        ) : (
          batches.map((batch) => <BatchCard key={batch.id} batch={batch} onConfirmed={handleConfirmed} />)
        )}
      </section>
    </div>
  );
}
