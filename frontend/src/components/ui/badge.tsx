import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-[10px] font-semibold tracking-wider whitespace-nowrap uppercase before:size-1.5 before:shrink-0 before:rounded-full",
  {
    variants: {
      tone: {
        accent: "bg-accent/12 text-accent before:bg-accent",
        alert: "bg-critical/12 text-critical before:bg-critical",
        positive: "bg-success/12 text-success before:bg-success",
        progress: "bg-info/12 text-info before:bg-info",
        idle: "bg-neutral/12 text-neutral before:bg-neutral",
        neutral: "bg-neutral/12 text-neutral before:bg-neutral",
      },
    },
    defaultVariants: {
      tone: "neutral",
    },
  }
);

interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children: ReactNode;
  className?: string;
  /** Hide the leading status dot for badges used as plain labels. */
  dot?: boolean;
}

export default function Badge({ tone, children, className, dot = true }: BadgeProps) {
  return (
    <span data-slot="badge" className={cn(badgeVariants({ tone }), !dot && "before:hidden", className)}>
      {children}
    </span>
  );
}

export { badgeVariants };
