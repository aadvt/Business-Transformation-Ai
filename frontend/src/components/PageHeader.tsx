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
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="font-display text-[30px] leading-[1.15] font-bold tracking-[-0.02em] text-ink">{title}</h1>
        <p className="mt-1.5 max-w-3xl text-[14px] leading-relaxed text-ink-muted">{subtitle}</p>
      </div>
      {actions}
    </div>
  );
}

export function SectionHeading({ children, count, action }: { children: ReactNode; count?: number; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <h2 className="font-display text-[15px] font-bold tracking-[-0.01em] text-ink">{children}</h2>
        {count !== undefined && (
          <span className="numeric rounded-full bg-surface-3 px-2 py-0.5 text-[11px] font-semibold text-ink-muted">
            {count}
          </span>
        )}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong bg-surface px-5 py-8 text-center text-[13px] text-ink-faint">
      {children}
    </div>
  );
}
