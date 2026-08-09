"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Bell,
  Building2,
  ChevronsUpDown,
  DatabaseZap,
  LayoutGrid,
  LogOut,
  Radar,
  Route,
  Settings,
  User,
  Wallet,
  Waypoints,
} from "lucide-react";
import clsx from "clsx";
import type { CSSProperties, ReactNode } from "react";
import { useDisruptions } from "@/lib/queries";
import { useLiveFeed } from "@/lib/live";
import { Toaster } from "@/components/ui/sonner";
import DemoControlBar from "@/components/DemoControlBar";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

// Grouped because a flat list of seven reads as a pile of screens; the three
// headings say what the workspace is *for* — watch it, act on it, set it up.
//
// `/vendors` is the ops-side list of vendors you actually trade with. The
// public self-registration directory still lives at its own standalone
// `/directory` route, reached from that page's Discover tab rather than from
// here — a workspace nav item should never eject you out of the workspace.
//
// `/network` is deliberately absent: the main dashboard now embeds the same
// map full-bleed, so a separate route for it would be a second door to one room.
const NAV_GROUPS: { heading: string; items: { href: string; label: string; icon: typeof LayoutGrid }[] }[] = [
  {
    heading: "Monitor",
    items: [
      { href: "/", label: "Main dashboard", icon: LayoutGrid },
      { href: "/waterfall", label: "Updates", icon: Bell },
    ],
  },
  {
    heading: "Respond",
    items: [
      { href: "/command", label: "Command", icon: Radar },
      { href: "/vendors", label: "Vendors", icon: Building2 },
      { href: "/settlement", label: "Transactions", icon: Wallet },
    ],
  },
  {
    heading: "Set up",
    items: [
      { href: "/onboarding", label: "Data sources", icon: DatabaseZap },
      { href: "/pipeline", label: "How it works", icon: Route },
    ],
  },
];

const NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

const CONNECTION = {
  open: { label: "Live", dot: "bg-success", hint: "Connected — the dashboard updates as events arrive." },
  connecting: { label: "Connecting", dot: "bg-warning animate-blink", hint: "Opening the live feed connection…" },
  closed: { label: "Reconnecting", dot: "bg-critical animate-blink", hint: "Live feed dropped — retrying automatically." },
} as const;

// The chrome publishes its own geometry so a route can lay something out
// against it — the main dashboard hangs a full-bleed map off these two
// variables, and `data-shell-main` lets it opt out of the content padding.
// Driving the real sidebar/header sizes from the same variables is what keeps
// the contract honest.
const SHELL_GEOMETRY = {
  "--shell-sidebar": "232px",
  "--shell-header": "56px",
} as CSSProperties;

// Micro-cap navigation labels. Written out rather than reusing the `eyebrow`
// utility because these need to carry their own state colour, and the utility
// pins the colour to ink-faint.
const NAV_LABEL = "text-[11px] font-semibold tracking-[0.06em] uppercase";

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { connectionState } = useLiveFeed();
  const { data } = useDisruptions("AWAITING_APPROVAL");
  const pendingApprovalsCount = data?.total ?? 0;
  const connection = CONNECTION[connectionState];
  const current = NAV_ITEMS.find((i) => i.href === pathname);

  return (
    <TooltipProvider>
      <div className="flex min-h-screen" style={SHELL_GEOMETRY}>
        <aside className="fixed inset-y-0 left-0 z-20 flex w-[var(--shell-sidebar)] flex-col border-r border-line bg-surface">
          <div className="flex h-[var(--shell-header)] items-center px-5">
            <Link
              href="/"
              className="flex items-center gap-2.5 rounded-md outline-offset-4 transition-opacity duration-200 hover:opacity-80"
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-ink">
                <Waypoints size={16} />
              </span>
              <span className="font-display text-[15px] leading-none font-bold tracking-[-0.02em] text-ink">
                SANJEEVANI
              </span>
            </Link>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 pt-3 pb-2">
            {NAV_GROUPS.map((group) => (
              <div key={group.heading} className="mb-4 last:mb-0">
                <span className="eyebrow block px-3 pb-1.5">{group.heading}</span>
                <div className="space-y-1">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const active = pathname === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={clsx(
                          "relative flex items-center gap-3 rounded-md px-3 py-2.5 outline-offset-2 transition-colors duration-200",
                          NAV_LABEL,
                          active
                            ? "bg-accent-dim text-accent"
                            : "text-ink-muted hover:bg-surface-2 hover:text-ink active:bg-surface-3"
                        )}
                      >
                        {active && <span className="absolute top-2 bottom-2 left-0 w-1 rounded-r-full bg-accent" />}
                        <Icon size={16} className={active ? "text-accent" : "text-ink-faint"} />
                        {item.label}
                        {item.href === "/" && pendingApprovalsCount > 0 && (
                          <span className="numeric ml-auto rounded-full bg-critical-dim px-1.5 py-px text-[10px] font-semibold text-critical">
                            {pendingApprovalsCount}
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          <div className="mt-auto border-t border-line px-5 py-4">
            <Tooltip>
              <TooltipTrigger className="flex items-center gap-2 rounded-sm outline-offset-4">
                <span className={clsx("size-1.5 rounded-full", connection.dot)} />
                <span className="text-[11px] font-medium text-ink-muted">{connection.label}</span>
              </TooltipTrigger>
              <TooltipContent side="right">{connection.hint}</TooltipContent>
            </Tooltip>
            <p className="mt-1.5 text-[11px] text-ink-faint">Mahe Industries · Chakan</p>
          </div>
        </aside>

        <div className="ml-[var(--shell-sidebar)] flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 h-[var(--shell-header)] border-b border-line bg-bg">
            <div className="mx-auto flex h-full w-full max-w-[1600px] items-center justify-between gap-6 px-6">
              <div className="flex min-w-0 items-center gap-2.5 text-[13px]">
                <span className="text-ink-faint">Sanjeevani</span>
                <span className="text-line-strong">/</span>
                <span className="font-display truncate text-[16px] font-bold tracking-[-0.01em] text-ink">
                  {current?.label ?? "Overview"}
                </span>
              </div>

              <div className="flex shrink-0 items-center gap-3">
                {pendingApprovalsCount > 0 && (
                  <Link
                    href="/"
                    className="flex items-center gap-1.5 rounded-full bg-critical-dim px-3 py-1.5 text-[11px] font-semibold text-critical outline-offset-2 transition-colors duration-200 hover:bg-critical hover:text-white"
                  >
                    <Activity size={12} />
                    <span className="numeric">{pendingApprovalsCount}</span> awaiting approval
                  </Link>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger className="flex cursor-pointer items-center gap-2 rounded-full py-1 pr-2.5 pl-1 text-[12px] font-medium text-ink-muted outline-offset-2 transition-colors duration-200 hover:bg-surface-2 hover:text-ink data-[state=open]:bg-surface-2 data-[state=open]:text-ink">
                    <span className="flex size-7 items-center justify-center rounded-full bg-accent-dim text-[10px] font-bold text-accent">
                      RK
                    </span>
                    Rajesh Kumar
                    <ChevronsUpDown size={12} className="text-ink-faint" />
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuLabel>Rajesh Kumar</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem>
                      <User />
                      Profile
                    </DropdownMenuItem>
                    <DropdownMenuItem>
                      <Settings />
                      Preferences
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive">
                      <LogOut />
                      Sign out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </header>

          <main
            key={pathname}
            data-shell-main
            className="animate-fade-in mx-auto w-full max-w-[1600px] flex-1 px-6 py-6"
          >
            {children}
          </main>
        </div>
      </div>
      <Toaster position="top-right" />
      <DemoControlBar />
    </TooltipProvider>
  );
}
