"use client";

import { useEffect, useState } from "react";
import { useSimulateTargets } from "@/lib/queries";
import { formatPaiseFull } from "@/lib/format";
import type { ScenarioKind } from "@/lib/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Button } from "@/components/ui/button";
import Skeleton from "@/components/ui/skeleton";

const SCENARIO_OPTIONS: { value: ScenarioKind; label: string }[] = [
  { value: "BACKED_OUT", label: "Backed out" },
  { value: "PRICE_HIKE", label: "Price hike" },
  { value: "DELAYED", label: "Delayed" },
  { value: "SHUT_DOWN", label: "Shut down" },
];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function SimulateDialog({
  open,
  onOpenChange,
  defaultScenario,
  onSubmit,
  submitting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultScenario: ScenarioKind;
  onSubmit: (body: { vendor_id: string; kind: ScenarioKind; effective_date: string }) => void;
  submitting: boolean;
}) {
  const { data: targets, isLoading } = useSimulateTargets();
  const [vendorId, setVendorId] = useState<string | null>(null);
  const [scenario, setScenario] = useState<ScenarioKind>(defaultScenario);
  const [effectiveDate, setEffectiveDate] = useState(todayIso());

  // Re-prime the form every time the dialog opens fresh (new default
  // scenario from whichever trigger button was clicked, first vendor
  // preselected so "Run simulation" is a valid single click if the
  // defaults are fine).
  useEffect(() => {
    if (!open) return;
    setScenario(defaultScenario);
    setEffectiveDate(todayIso());
    setVendorId(targets?.[0]?.vendor_id ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultScenario]);

  useEffect(() => {
    if (open && !vendorId && targets?.[0]) setVendorId(targets[0].vendor_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targets]);

  const selectedTarget = targets?.find((t) => t.vendor_id === vendorId) ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run a simulation</DialogTitle>
          <DialogDescription>Pick a vendor and a scenario — this drives the impact graph on the canvas.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div>
            <label className="eyebrow mb-1.5 block">Vendor</label>
            {isLoading ? (
              <Skeleton className="h-9" />
            ) : (
              <Select value={vendorId} onValueChange={(v) => setVendorId(v as string)}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a vendor">
                    {selectedTarget ? selectedTarget.name : "Choose a vendor"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(targets ?? []).map((target) => (
                    <SelectItem key={target.vendor_id} value={target.vendor_id}>
                      <span className="font-medium text-ink">{target.name}</span>
                      <span className="text-[11px] text-ink-muted">
                        {target.category} · {formatPaiseFull(target.est_exposure_paise)} exposure
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div>
            <label className="eyebrow mb-1.5 block">Scenario</label>
            <ToggleGroup
              className="w-full justify-between"
              value={[scenario]}
              onValueChange={(v) => {
                if (v.length > 0) setScenario(v[0] as ScenarioKind);
              }}
            >
              {SCENARIO_OPTIONS.map((opt) => (
                <ToggleGroupItem key={opt.value} value={opt.value} className="flex-1 text-center">
                  {opt.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>

          <div>
            <label className="eyebrow mb-1.5 block">Effective</label>
            <input
              type="date"
              value={effectiveDate}
              onChange={(e) => setEffectiveDate(e.target.value)}
              className="h-9 w-full rounded-md border border-line bg-surface-2 px-3 text-[13px] text-ink outline-none transition-colors duration-100 hover:border-line-strong focus:border-accent"
            />
          </div>
        </div>

        <DialogFooter>
          <Button
            disabled={!vendorId || submitting}
            onClick={() => vendorId && onSubmit({ vendor_id: vendorId, kind: scenario, effective_date: effectiveDate })}
          >
            {submitting ? "Starting…" : "Run simulation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
