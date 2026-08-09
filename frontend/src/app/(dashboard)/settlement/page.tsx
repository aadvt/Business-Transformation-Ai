"use client";

import { useId, useState } from "react";
import { ChevronDown, Wallet } from "lucide-react";
import clsx from "clsx";
import { toast } from "sonner";
import { useConfirmSettlementBatch, useExecuteSettlementBatch, useSettlementBatches } from "@/lib/queries";
import { formatPaiseFull } from "@/lib/format";
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

const STATUS_TONE: Record<string, "idle" | "progress" | "positive" | "accent" | "neutral"> = {
  PENDING: "neutral",
  EXECUTING: "accent",
  CONFIRMED: "positive",
};

/** Compact metric card: micro-caps label over the figure, nothing else. */
function SummaryTile({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "positive" }) {
  return (
    <div className="panel px-4 py-3.5">
      <p className="eyebrow">{label}</p>
      <p
        className={clsx(
          "numeric mt-2.5 text-[22px] leading-none font-semibold tracking-tight",
          tone === "positive" ? "text-success" : "text-ink"
        )}
        data-numeric
      >
        {value}
      </p>
    </div>
  );
}

interface BatchCardProps {
  batch: SettlementBatch;
  onConfirmed: (batch: SettlementBatch, handoff?: TransactionAgentHandoff | null) => void;
}

function BatchCard({ batch, onConfirmed }: BatchCardProps) {
  const confirm = useConfirmSettlementBatch();
  const execute = useExecuteSettlementBatch();
  const [confirmingExecute, setConfirmingExecute] = useState(false);
  const [showLines, setShowLines] = useState(false);
  const linesId = useId();

  return (
    <div className="panel-flush">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4">
        <div className="flex min-w-[11rem] flex-1 items-center gap-3">
          <span className="numeric text-[13px] font-semibold text-ink" data-numeric>
            {batch.month}
          </span>
          <Badge tone={STATUS_TONE[batch.status] ?? "neutral"} className="rounded-full px-2 py-0.5">
            {STATUS_LABEL[batch.status] ?? batch.status}
          </Badge>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="numeric text-[17px] leading-tight font-semibold text-ink" data-numeric>
              {batch.total_display}
            </p>
            <p className="mt-0.5 text-[11px] text-ink-faint">
              {batch.lines.length} line{batch.lines.length === 1 ? "" : "s"}
            </p>
          </div>

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

          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setShowLines((v) => !v)}
            aria-expanded={showLines}
            aria-controls={linesId}
            aria-label={showLines ? `Hide invoice lines for ${batch.month}` : `Show invoice lines for ${batch.month}`}
          >
            <ChevronDown size={14} className={clsx("transition-transform duration-200", showLines && "rotate-180")} />
          </Button>
        </div>
      </div>

      {showLines && (
        <div id={linesId} className="border-t border-line">
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
      )}
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
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <SummaryTile label="Outstanding" value={formatPaiseFull(outstandingPaise)} />
          <SummaryTile label="Batches" value={String(batches.length)} />
          <SummaryTile label="Invoice lines" value={String(lineCount)} />
          <SummaryTile label="Confirmed" value={String(confirmedCount)} tone="positive" />
        </div>
      )}

      <section>
        <SectionHeading count={batches.length}>Payout batches</SectionHeading>
        {isLoading ? (
          <Skeleton className="h-44" />
        ) : batches.length === 0 ? (
          <EmptyState>No settlement batches yet.</EmptyState>
        ) : (
          <div className="flex flex-col gap-3">
            {batches.map((batch) => (
              <BatchCard key={batch.id} batch={batch} onConfirmed={handleConfirmed} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
