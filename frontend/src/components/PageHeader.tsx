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
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-[19px] leading-tight font-semibold tracking-[-0.01em] text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-[13px] text-ink-muted">{subtitle}</p>
      </div>
      {actions}
    </div>
  );
}

export function SectionHeading({ children, count, action }: { children: ReactNode; count?: number; action?: ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <h2 className="text-[13px] font-semibold text-ink">{children}</h2>
        {count !== undefined && (
          <span className="numeric rounded-sm bg-surface-2 px-1.5 py-px text-[10px] text-ink-muted">{count}</span>
        )}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-ink-faint">
      {children}
    </div>
  );
}
