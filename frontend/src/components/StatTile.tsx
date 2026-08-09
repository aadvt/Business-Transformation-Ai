"use client";

import type { ComponentType } from "react";
import clsx from "clsx";

interface StatTileProps {
  label: string;
  value: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone?: "default" | "alert" | "positive";
}

const TONE_VALUE: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "text-ink",
  alert: "text-critical",
  positive: "text-success",
};

const TONE_CHIP: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "bg-surface-3 text-ink-muted",
  alert: "bg-critical/12 text-critical",
  positive: "bg-success/12 text-success",
};

const TONE_BAR: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "bg-line-strong",
  alert: "bg-critical",
  positive: "bg-success",
};

export default function StatTile({ label, value, icon: Icon, tone = "default" }: StatTileProps) {
  return (
    <div className="relative overflow-hidden bg-surface p-4 pl-[18px]">
      <span className={clsx("absolute top-0 bottom-0 left-0 w-[3px]", TONE_BAR[tone])} />
      <div className="mb-3 flex items-center justify-between">
        <p className="eyebrow">{label}</p>
        <span className={clsx("flex size-6 shrink-0 items-center justify-center rounded-md", TONE_CHIP[tone])}>
          <Icon size={13} />
        </span>
      </div>
      <p className={clsx("numeric text-[28px] font-semibold leading-none tracking-tight", TONE_VALUE[tone])}>
        {value}
      </p>
    </div>
  );
}
