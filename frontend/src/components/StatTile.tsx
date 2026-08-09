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

export default function StatTile({ label, value, icon: Icon, tone = "default" }: StatTileProps) {
  return (
    <div className="bg-surface p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="eyebrow">{label}</p>
        <Icon size={13} className="text-ink-faint" />
      </div>
      <p className={clsx("numeric text-[26px] font-medium leading-none", TONE_VALUE[tone])}>{value}</p>
    </div>
  );
}
