"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, LayoutGrid, Network, User, Wallet, Workflow } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import type { ReactNode } from "react";
import { useDisruptions } from "@/lib/queries";
import { useLiveFeed } from "@/lib/live";

const NAV_ITEMS = [
  { href: "/", label: "War Room", icon: LayoutGrid },
  { href: "/waterfall", label: "Live Pipeline", icon: Workflow },
  { href: "/settlement", label: "Settlement", icon: Wallet },
  { href: "/network", label: "Network", icon: Network },
];

const CONNECTION_COPY = {
  open: { label: "Live", dot: "bg-positive", glow: "shadow-[0_0_10px_var(--color-positive)]" },
  connecting: { label: "Connecting…", dot: "bg-accent", glow: "shadow-[0_0_10px_var(--color-accent)]" },
  closed: { label: "Reconnecting…", dot: "bg-alert", glow: "shadow-[0_0_10px_var(--color-alert)]" },
} as const;

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { connectionState } = useLiveFeed();
  const { data } = useDisruptions("AWAITING_APPROVAL");
  const pendingApprovalsCount = data?.total ?? 0;
  const connection = CONNECTION_COPY[connectionState];

  return (
    <div className="flex min-h-screen">
      <aside className="glass-panel sticky top-0 z-20 m-3 mr-0 flex h-[calc(100vh-1.5rem)] w-60 shrink-0 flex-col rounded-3xl">
        <div className="px-5 py-6">
          <Link href="/" className="group block">
            <div className="flex items-center gap-2.5">
              <motion.span
                className="h-7 w-7 rounded-xl bg-gradient-to-br from-accent-strong to-accent shadow-lg shadow-accent/40"
                whileHover={{ rotate: 90, scale: 1.08 }}
                transition={{ type: "spring", stiffness: 260, damping: 18 }}
              />
              <span className="text-[1.0625rem] font-bold tracking-tight text-ink">SANJEEVANI</span>
            </div>
            <p className="mt-1.5 pl-[2.375rem] text-[0.625rem] font-medium tracking-[0.16em] text-ink-faint uppercase">
              Supply Chain Command
            </p>
          </Link>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors duration-200",
                  active ? "text-accent-strong" : "text-ink-muted hover:text-ink"
                )}
              >
                {active && (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 rounded-xl bg-accent/12 ring-1 ring-accent/25"
                    transition={{ type: "spring", stiffness: 380, damping: 32 }}
                  />
                )}
                <Icon size={17} className="relative z-10" />
                <span className="relative z-10">{item.label}</span>
                {item.href === "/" && pendingApprovalsCount > 0 && (
                  <motion.span
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="relative z-10 ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-alert px-1.5 text-[0.625rem] font-bold text-white shadow-lg shadow-alert/40"
                  >
                    {pendingApprovalsCount}
                  </motion.span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="mx-3 mb-3 rounded-2xl bg-white/[0.03] px-4 py-3">
          <div className="flex items-center gap-2 text-xs">
            <span
              className={clsx(
                "h-1.5 w-1.5 rounded-full",
                connection.dot,
                connection.glow,
                connectionState !== "closed" && "animate-live-dot"
              )}
            />
            <span className="text-ink-muted">{connection.label}</span>
          </div>
          <p className="mt-1 text-[0.625rem] text-ink-faint">Powered by watsonx · Granite</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-end gap-4 px-8 py-4">
          <div className="glass flex items-center gap-4 rounded-2xl px-4 py-2">
            <motion.button
              type="button"
              aria-label="Notifications"
              whileTap={{ scale: 0.9 }}
              className="relative cursor-pointer text-ink-muted transition-colors hover:text-ink"
            >
              <Bell size={17} />
              {pendingApprovalsCount > 0 && (
                <span className="absolute -top-1 -right-1.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-alert px-1 text-[0.5rem] font-bold text-white">
                  {pendingApprovalsCount}
                </span>
              )}
            </motion.button>
            <span className="h-4 w-px bg-white/10" />
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-accent/30 to-accent/5 ring-1 ring-white/10">
                <User size={13} />
              </span>
              Rajesh Kumar
            </div>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.main
            key={pathname}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="mx-auto w-full max-w-[1500px] flex-1 px-8 pt-2 pb-10"
          >
            {children}
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  );
}
