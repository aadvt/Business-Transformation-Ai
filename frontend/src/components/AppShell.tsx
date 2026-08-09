"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bell, Building2, ChevronsUpDown, LayoutGrid, LogOut, Settings, User, Wallet } from "lucide-react";
import clsx from "clsx";
import type { ReactNode } from "react";
import { useDisruptions } from "@/lib/queries";
import { useLiveFeed } from "@/lib/live";
import { Toaster } from "@/components/ui/sonner";
import DemoControlBar from "@/components/DemoControlBar";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV_ITEMS = [
  { href: "/", label: "Main dashboard", icon: LayoutGrid },
  { href: "/settlement", label: "Transactions", icon: Wallet },
  { href: "/directory", label: "Vendors", icon: Building2 },
  { href: "/waterfall", label: "Updates", icon: Bell },
];

const CONNECTION = {
  open: { label: "Live", dot: "bg-success", hint: "Connected — the dashboard updates as events arrive." },
  connecting: { label: "Connecting", dot: "bg-warning animate-blink", hint: "Opening the live feed connection…" },
  closed: { label: "Reconnecting", dot: "bg-critical animate-blink", hint: "Live feed dropped — retrying automatically." },
} as const;

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { connectionState } = useLiveFeed();
  const { data } = useDisruptions("AWAITING_APPROVAL");
  const pendingApprovalsCount = data?.total ?? 0;
  const connection = CONNECTION[connectionState];
  const current = NAV_ITEMS.find((i) => i.href === pathname);

  return (
    <TooltipProvider>
      <div className="flex min-h-screen">
        <aside className="fixed inset-y-0 left-0 z-20 flex w-[212px] flex-col border-r border-line bg-surface">
          <div className="flex h-12 items-center gap-2 border-b border-line px-4">
            <span className="h-4 w-1 rounded-sm bg-accent" />
            <Link href="/" className="text-[13px] font-semibold tracking-wide text-ink">
              SANJEEVANI
            </Link>
          </div>

          <div className="px-4 pt-4 pb-2">
            <span className="eyebrow">Workspace</span>
          </div>

          <nav className="flex-1 space-y-0.5 px-2">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors duration-100",
                    active ? "bg-surface-2 font-medium text-ink" : "text-ink-muted hover:bg-surface-2 hover:text-ink"
                  )}
                >
                  {active && <span className="absolute top-1.5 bottom-1.5 -left-2 w-0.5 rounded-r-sm bg-accent" />}
                  <Icon size={15} className={active ? "text-accent" : ""} />
                  {item.label}
                  {item.href === "/" && pendingApprovalsCount > 0 && (
                    <span className="numeric ml-auto rounded-sm bg-critical/15 px-1.5 py-px text-[10px] font-semibold text-critical">
                      {pendingApprovalsCount}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>

          <Separator className="mx-4 w-auto" />

          <div className="px-4 py-3">
            <Tooltip>
              <TooltipTrigger className="flex items-center gap-2">
                <span className={clsx("h-1.5 w-1.5 rounded-full", connection.dot)} />
                <span className="text-[11px] text-ink-muted">{connection.label}</span>
              </TooltipTrigger>
              <TooltipContent side="right">{connection.hint}</TooltipContent>
            </Tooltip>
            <p className="mt-1 text-[10px] text-ink-faint">Mahe Industries · Chakan</p>
          </div>
        </aside>

        <div className="ml-[212px] flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-10 flex h-12 items-center justify-between border-b border-line bg-bg/95 px-6 backdrop-blur-sm">
            <div className="flex items-center gap-2 text-[13px]">
              <span className="text-ink-faint">Sanjeevani</span>
              <span className="text-ink-faint">/</span>
              <span className="font-medium text-ink">{current?.label ?? "Overview"}</span>
            </div>

            <div className="flex items-center gap-3">
              {pendingApprovalsCount > 0 && (
                <Link
                  href="/"
                  className="flex items-center gap-1.5 rounded-md bg-critical/10 px-2 py-1 text-[11px] font-medium text-critical transition-colors duration-100 hover:bg-critical/15"
                >
                  <Activity size={12} />
                  {pendingApprovalsCount} awaiting approval
                </Link>
              )}
              <Separator orientation="vertical" className="h-5" />
              <DropdownMenu>
                <DropdownMenuTrigger className="flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-1 text-[12px] text-ink-muted transition-colors duration-100 hover:bg-surface-2 hover:text-ink">
                  <span className="flex h-5 w-5 items-center justify-center rounded-sm bg-surface-2 text-[10px] font-semibold text-ink">
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
          </header>

          <main key={pathname} className="animate-fade-in mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
            {children}
          </main>
        </div>
      </div>
      <Toaster position="top-right" />
      <DemoControlBar />
    </TooltipProvider>
  );
}
