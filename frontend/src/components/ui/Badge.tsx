import clsx from "clsx";
import type { ReactNode } from "react";

type BadgeTone = "accent" | "alert" | "positive" | "progress" | "idle" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  accent: "bg-accent/12 text-accent-strong ring-1 ring-accent/25",
  alert: "bg-alert/10 text-alert ring-1 ring-alert/25",
  positive: "bg-positive/10 text-positive ring-1 ring-positive/25",
  progress: "bg-progress/10 text-progress ring-1 ring-progress/25",
  idle: "bg-idle/10 text-idle ring-1 ring-idle/25",
  neutral: "bg-glass text-ink-muted ring-1 ring-glass-border",
};

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}

export default function Badge({ tone = "neutral", children, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-[0.6875rem] font-semibold uppercase tracking-wide whitespace-nowrap",
        TONE_CLASSES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
