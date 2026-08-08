"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";

export default function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="bg-gradient-to-br from-white via-white to-white/45 bg-clip-text text-[2.125rem] leading-none font-semibold tracking-[-0.02em] text-transparent"
        >
          {title}
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.07, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="mt-2.5 max-w-2xl text-[0.9375rem] text-ink-muted"
        >
          {subtitle}
        </motion.p>
      </div>
      {actions}
    </div>
  );
}

export function SectionHeading({ children, count }: { children: ReactNode; count?: number }) {
  return (
    <div className="mb-4 flex items-center gap-3">
      <span className="h-4 w-[3px] rounded-full bg-gradient-to-b from-accent-strong to-accent/20" />
      <h2 className="text-[0.9375rem] font-semibold tracking-tight text-ink">{children}</h2>
      {count !== undefined && (
        <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[0.6875rem] font-medium text-ink-muted">
          {count}
        </span>
      )}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.015] px-6 py-8 text-center text-sm text-ink-muted">
      {children}
    </div>
  );
}
