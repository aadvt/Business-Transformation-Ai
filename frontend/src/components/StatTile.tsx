"use client";

import type { ComponentType } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";

interface StatTileProps {
  label: string;
  value: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone?: "default" | "alert" | "positive";
}

const TONE_ICON: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "text-ink-muted",
  alert: "text-alert",
  positive: "text-positive",
};

const TONE_BG: Record<NonNullable<StatTileProps["tone"]>, string> = {
  default: "bg-ink-muted/12",
  alert: "bg-alert/12",
  positive: "bg-positive/12",
};

export default function StatTile({ label, value, icon: Icon, tone = "default" }: StatTileProps) {
  return (
    <motion.div
      className="glass rounded-2xl p-5 flex items-start gap-3.5"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -3 }}
      transition={{ type: "spring", stiffness: 300, damping: 30 }}
    >
      <div className={clsx("rounded-lg p-2 mt-0.5 shrink-0", TONE_BG[tone])}>
        <Icon size={20} className={clsx(TONE_ICON[tone])} />
      </div>
      <div>
        <p className="tabular-money text-2xl leading-tight font-semibold text-ink">{value}</p>
        <p className="mt-0.5 text-[0.8125rem] text-ink-muted">{label}</p>
      </div>
    </motion.div>
  );
}
