"use client";

import type { ComponentType } from "react";
import clsx from "clsx";

interface StatTileProps {
  label: string;
  value: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone?: "default" | "alert" | "positive";
}

// Tone is status, not decoration: it reaches the reader through the icon chip's
// container tint and the figure's colour. A thick coloured rule down the edge
// of the card would be the same information shouted, so there isn't one.
const TONE_VALUE: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "text-ink",
  alert: "text-critical",
  positive: "text-success",
};

const TONE_CHIP: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "bg-neutral-dim text-neutral",
  alert: "bg-critical-dim text-critical",
  positive: "bg-success-dim text-success",
};

export default function StatTile({ label, value, icon: Icon, tone = "default" }: StatTileProps) {
  return (
    <div className="shadow-panel flex flex-col justify-between gap-4 rounded-lg bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="eyebrow pt-1">{label}</p>
        <span className={clsx("flex size-9 shrink-0 items-center justify-center rounded-md", TONE_CHIP[tone])}>
          <Icon size={16} />
        </span>
      </div>
      <p className={clsx("numeric text-[30px] leading-none font-semibold", TONE_VALUE[tone])}>{value}</p>
    </div>
  );
}
