"use client";

import { useMemo, useState } from "react";
import { Checkbox, Button, ToastNotification } from "@carbon/react";
import { Wallet, CheckmarkFilled } from "@carbon/icons-react";
import { useSanjeevani } from "@/lib/store";
import { formatINR, formatINRFull } from "@/lib/format";
import StatTile from "@/components/StatTile";

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  staged: "Staged for payout",
  settled: "Settled",
};

export default function SettlementPage() {
  const { dues, settle } = useSanjeevani();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmation, setConfirmation] = useState<{ count: number; amount: number } | null>(null);

  const settleable = useMemo(() => dues.filter((d) => d.status !== "settled"), [dues]);
  const totalDue = useMemo(() => settleable.reduce((sum, d) => sum + d.amountINR, 0), [settleable]);
  const totalSelectedAmount = useMemo(
    () => settleable.filter((d) => selected.has(d.id)).reduce((sum, d) => sum + d.amountINR, 0),
    [settleable, selected]
  );
  const settledCount = dues.filter((d) => d.status === "settled").length;

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected((prev) => (prev.size === settleable.length ? new Set() : new Set(settleable.map((d) => d.id))));
  }

  function handleSettle() {
    if (selected.size === 0) return;
    const ids = Array.from(selected);
    settle(ids);
    setConfirmation({ count: ids.length, amount: totalSelectedAmount });
    setSelected(new Set());
  }

  return (
    <div>
      <h1 className="sanjeevani-page-title">Settlement</h1>
      <p className="sanjeevani-page-subtitle">
        One consolidated batch instead of dozens of individual payouts. Review, then approve — the transaction agent stages the UPI
        payout for execution.
      </p>

      <div className="stat-grid">
        <StatTile label="Total outstanding" value={formatINR(totalDue)} icon={Wallet} tone="alert" />
        <StatTile label="Vendors due" value={String(settleable.length)} icon={Wallet} />
        <StatTile label="Settled this cycle" value={String(settledCount)} icon={CheckmarkFilled} tone="positive" />
      </div>

      {confirmation && (
        <ToastNotification
          kind="success"
          title="Settlement staged"
          subtitle={`${confirmation.count} vendor${confirmation.count > 1 ? "s" : ""} · ${formatINRFull(
            confirmation.amount
          )} — payout batch handed to the transaction agent for execution.`}
          timeout={6000}
          onClose={() => setConfirmation(null)}
          onCloseButtonClick={() => setConfirmation(null)}
          className="sanjeevani-toast"
        />
      )}

      <div className="settlement-table">
        <div className="settlement-table__row settlement-table__row--head">
          <span className="settlement-table__checkbox">
            <Checkbox
              id="select-all-dues"
              labelText=""
              hideLabel
              checked={selected.size > 0 && selected.size === settleable.length}
              indeterminate={selected.size > 0 && selected.size < settleable.length}
              onChange={toggleAll}
              disabled={settleable.length === 0}
            />
          </span>
          <span>Vendor</span>
          <span>Due date</span>
          <span>Status</span>
          <span className="settlement-table__amount-head">Amount</span>
        </div>

        {dues.map((due) => (
          <div className={`settlement-table__row ${due.status === "settled" ? "settlement-table__row--settled" : ""}`} key={due.id}>
            <span className="settlement-table__checkbox">
              <Checkbox
                id={`due-${due.id}`}
                labelText=""
                hideLabel
                checked={selected.has(due.id)}
                onChange={() => toggle(due.id)}
                disabled={due.status === "settled"}
              />
            </span>
            <span className="settlement-table__name">{due.vendorName}</span>
            <span>{due.dueDate}</span>
            <span className={`settlement-table__status settlement-table__status--${due.status}`}>{STATUS_LABEL[due.status]}</span>
            <span className="settlement-table__amount">{formatINRFull(due.amountINR)}</span>
          </div>
        ))}
      </div>

      <div className="settlement-actions">
        <span className="settlement-actions__summary">
          {selected.size > 0
            ? `${selected.size} selected · ${formatINRFull(totalSelectedAmount)}`
            : "Select vendors to include in this settlement batch"}
        </span>
        <Button kind="primary" renderIcon={Wallet} disabled={selected.size === 0} onClick={handleSettle}>
          One-click settle
        </Button>
      </div>
    </div>
  );
}
