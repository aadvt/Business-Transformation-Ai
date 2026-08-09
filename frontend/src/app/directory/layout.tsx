import type { ReactNode } from "react";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";

// Deliberately its own visual language — light, plain, "government registry
// meets modern SaaS" — not another dark ops-terminal page of the main app.
// No AppShell: this is meant to read as a separate public service that
// happens to be linked from the dashboard, not vice versa. It still speaks in
// the same Soft Logic tokens, so the two never look like different products.
export default function DirectoryLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-bg font-sans text-ink">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <Link
            href="/directory"
            className="flex items-center gap-3 rounded-md outline-offset-4 transition-opacity duration-200 hover:opacity-80"
          >
            <span className="flex size-9 items-center justify-center rounded-md bg-accent text-accent-ink">
              <ShieldCheck size={18} />
            </span>
            <span>
              <span className="font-display block text-[16px] font-bold tracking-[-0.01em] text-ink">
                Sanjeevani Vendor Directory
              </span>
              <span className="block text-[12px] text-ink-muted">Open, verified, free to list.</span>
            </span>
          </Link>
          <nav className="flex items-center gap-4 text-[13px] font-medium">
            <Link
              href="/directory"
              className="rounded-md px-3 py-2 text-ink-muted outline-offset-2 transition-colors duration-200 hover:bg-surface-2 hover:text-ink"
            >
              Search
            </Link>
            <Link
              href="/directory/register"
              className="rounded-md bg-accent px-4 py-2 text-accent-ink outline-offset-2 transition-colors duration-200 hover:bg-accent-bright"
            >
              List your business
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>

      <footer className="border-t border-line bg-surface py-6">
        <div className="mx-auto max-w-5xl px-6 text-[12px] text-ink-faint">
          Every listing is checked against GSTIN structure, checksum, and Udyam format before it&apos;s marked verified —
          see the evidence on any vendor&apos;s page.
        </div>
      </footer>
    </div>
  );
}
