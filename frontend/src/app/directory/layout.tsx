import type { ReactNode } from "react";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";

// Deliberately its own visual language — light, plain, "government registry
// meets modern SaaS" — not another dark ops-terminal page of the main app.
// No AppShell: this is meant to read as a separate public service that
// happens to be linked from the dashboard, not vice versa.
export default function DirectoryLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f7f7f5] font-sans text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-6 py-4">
          <Link href="/directory" className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-900 text-white">
              <ShieldCheck size={17} />
            </span>
            <span>
              <span className="block text-[15px] font-semibold tracking-tight text-slate-900">
                Sanjeevani Vendor Directory
              </span>
              <span className="block text-[12px] text-slate-500">Open, verified, free to list.</span>
            </span>
          </Link>
          <nav className="flex items-center gap-5 text-[13px] font-medium text-slate-600">
            <Link href="/directory" className="hover:text-slate-900">
              Search
            </Link>
            <Link
              href="/directory/register"
              className="rounded-md bg-slate-900 px-3.5 py-1.5 text-white transition-colors hover:bg-slate-700"
            >
              List your business
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>

      <footer className="border-t border-slate-200 bg-white py-6">
        <div className="mx-auto max-w-5xl px-6 text-[12px] text-slate-400">
          Every listing is checked against GSTIN structure, checksum, and Udyam format before it's marked verified —
          see the evidence on any vendor&apos;s page.
        </div>
      </footer>
    </div>
  );
}
