import clsx from "clsx";
import type { ReactNode } from "react";

type BadgeTone = "accent" | "alert" | "positive" | "progress" | "idle" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  accent: "bg-accent/12 text-accent",
  alert: "bg-critical/12 text-critical",
  positive: "bg-success/12 text-success",
  progress: "bg-info/12 text-info",
  idle: "bg-neutral/12 text-neutral",
  neutral: "bg-neutral/12 text-neutral",
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
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap",
        TONE_CLASSES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}
