"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Building2, Compass, MapPin, PackageSearch, Search, X } from "lucide-react";
import clsx from "clsx";
import { api, ApiError } from "@/lib/api";
import { usePublicVendors, useVendorDues, useVendors } from "@/lib/queries";
import { formatPaiseFull, formatTimeAgo } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import VerificationBadge from "@/components/VerificationBadge";
import Skeleton from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  MemorySource,
  PublicVendor,
  PublicVendorSearchParams,
  Vendor,
  VendorDue,
} from "@/lib/types";

// Both tabs render the same five-column row so the page reads as one list with
// two sources, not two products stapled together. Reliability gets a fixed
// column because a meter that reflows with the viewport can't be compared
// down the page.
const ROW_GRID =
  "grid grid-cols-2 items-center gap-x-4 gap-y-2 px-4 lg:grid-cols-[minmax(0,2.3fr)_minmax(0,1.3fr)_150px_minmax(0,1.2fr)_minmax(0,0.9fr)]";

const FIELD =
  "h-9 rounded-md border border-line bg-surface px-3 text-[13px] text-ink transition-colors duration-200 placeholder:text-ink-faint hover:border-line-strong focus:border-accent";

// Language codes come off the wire as ISO-639-1; anything unmapped falls back
// to the raw code rather than being hidden.
const LANGUAGE_LABEL: Record<string, string> = {
  hi: "Hindi",
  mr: "Marathi",
  en: "English",
  ta: "Tamil",
  te: "Telugu",
  gu: "Gujarati",
  kn: "Kannada",
  bn: "Bengali",
  pa: "Punjabi",
};

const MEMORY_NOTE: Record<MemorySource, string> = {
  SUPERMEMORY: "Briefing recalled from Supermemory.",
  DB_ONLY: "Briefing assembled from order history alone — no memory service.",
  UNAVAILABLE: "Memory service unavailable; this briefing may be stale.",
};

// Reliability is a single 0-100 figure, which tells you nothing until you know
// what "68" means for a supplier. The bands turn it into a judgement, and the
// bar makes a weak vendor visible before you've read the number.
const RELIABILITY_BANDS = [
  { min: 85, label: "Strong", bar: "bg-success", text: "text-success" },
  { min: 70, label: "Steady", bar: "bg-info", text: "text-info" },
  { min: 55, label: "Watch", bar: "bg-warning", text: "text-warning" },
  { min: 0, label: "Weak", bar: "bg-critical", text: "text-critical" },
];

function reliabilityBand(score: number) {
  return RELIABILITY_BANDS.find((b) => score >= b.min) ?? RELIABILITY_BANDS[RELIABILITY_BANDS.length - 1];
}

function languageLabel(code: string): string {
  return LANGUAGE_LABEL[code] ?? code.toUpperCase();
}

// VendorContext ships raw paise with no `_display` counterpart the way Vendor
// does, so its money formats here rather than through formatPaiseFull, which
// rounds to whole rupees. Two shapes, because the figures sit on different
// scales: unit prices are single-rupee and are read against each other
// (₹14.50 agreed vs ₹16.00 ceiling), so they always carry paise; the
// human-approval ceiling is in lakhs, where ".00" is noise.
function inr(paise: number, fractionDigits: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(paise / 100);
}

const formatUnitPrice = (paise: number) => inr(paise, 2);
const formatCeiling = (paise: number) => inr(paise, paise % 100 === 0 ? 0 : 2);

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

/** Every keystroke would otherwise mint a new query key and refetch. */
function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

function ReliabilityMeter({ score, className }: { score: number; className?: string }) {
  const band = reliabilityBand(score);
  return (
    <div className={clsx("flex items-center gap-2.5", className)}>
      {/* Decorative: the figure beside it carries the same value for anyone
          who can't see the fill. */}
      <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
        <div
          className={clsx("h-full rounded-full transition-[width] duration-300", band.bar)}
          style={{ width: `${Math.min(100, Math.max(2, score))}%` }}
        />
      </div>
      <span className={clsx("numeric shrink-0 text-[12.5px] font-semibold", band.text)}>{score}</span>
    </div>
  );
}

function DisputeChip({ count }: { count: number }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-warning-dim px-1.5 py-px text-[10px] font-semibold text-warning">
      <AlertTriangle size={10} />
      <span className="numeric">{count}</span> dispute{count === 1 ? "" : "s"}
    </span>
  );
}

function LanguagePills({ codes }: { codes: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {codes.map((code) => (
        <span
          key={code}
          className="rounded-full bg-surface-3 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-ink-muted uppercase"
        >
          {code}
        </span>
      ))}
    </div>
  );
}

function ColumnHeader({ columns }: { columns: { label: string; align?: "right" }[] }) {
  return (
    <div className={clsx(ROW_GRID, "hidden border-b border-line bg-surface-2 py-2 lg:grid")}>
      {columns.map((col) => (
        <span key={col.label} className={clsx("eyebrow", col.align === "right" && "text-right")}>
          {col.label}
        </span>
      ))}
    </div>
  );
}

function RowSkeletons({ count = 6 }: { count?: number }) {
  return (
    <div className="divide-y divide-line">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className={clsx(ROW_GRID, "py-4")}>
          <div className="col-span-2 lg:col-span-1">
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="mt-2 h-2.5 w-24" />
          </div>
          <Skeleton className="h-3 w-28" />
          <Skeleton className="h-1.5 w-full" />
          <Skeleton className="h-3 w-24" />
          <Skeleton className="ml-auto h-3 w-16" />
        </div>
      ))}
    </div>
  );
}

function EmptyBlock({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Building2;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
      <span className="mx-auto mb-4 flex size-11 items-center justify-center rounded-md bg-surface-3 text-ink-faint">
        <Icon size={20} />
      </span>
      <p className="font-display mb-1.5 text-[15px] font-bold text-ink">{title}</p>
      <p className="mx-auto max-w-md text-[13px] leading-relaxed text-ink-muted">{children}</p>
    </div>
  );
}

function SummaryStat({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "alert" }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p
        className={clsx(
          "numeric mt-1 text-[19px] leading-none font-semibold",
          tone === "alert" ? "text-critical" : "text-ink"
        )}
        data-numeric
      >
        {value}
      </p>
    </div>
  );
}

// ---- Detail dialog --------------------------------------------------------

function DetailField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow">{label}</p>
      <div className="mt-1 text-[13px] break-words text-ink">{children}</div>
    </div>
  );
}

function DetailBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md bg-surface-2 p-4">
      <h3 className="font-display mb-3 text-[13px] font-bold text-ink">{title}</h3>
      {children}
    </section>
  );
}

function VendorDetailDialog({
  vendor,
  due,
  onClose,
}: {
  vendor: Vendor;
  due: VendorDue | undefined;
  onClose: () => void;
}) {
  const { data: context, isPending, error } = useQuery({
    queryKey: ["vendorContext", vendor.id],
    queryFn: () => api.getVendorContext(vendor.id),
    // A 404 is an answer here, not a failure — the agent simply has no
    // negotiation history with this vendor yet, which is the common case for
    // a vendor you've never had a disruption with. Retrying it three times
    // just leaves the dialog on skeletons for seconds.
    retry: (failureCount, err) => !(err instanceof ApiError && err.status === 404) && failureCount < 2,
  });

  const noContextYet = error instanceof ApiError && error.status === 404;
  const band = reliabilityBand(vendor.reliability_score_0_100);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[86vh] gap-4 overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-[18px]">{vendor.name}</DialogTitle>
          <DialogDescription>
            {vendor.category} · {vendor.city}, {vendor.state}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-md bg-surface-2 p-3">
            <p className="eyebrow">Reliability</p>
            <p className={clsx("numeric mt-1 text-[17px] leading-none font-semibold", band.text)}>
              {vendor.reliability_score_0_100}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">{band.label}</p>
          </div>
          <div className="rounded-md bg-surface-2 p-3">
            <p className="eyebrow">On time</p>
            <p className="numeric mt-1 text-[17px] leading-none font-semibold text-ink">
              {Math.round(vendor.on_time_rate * 100)}%
            </p>
          </div>
          <div className="rounded-md bg-surface-2 p-3">
            <p className="eyebrow">Orders</p>
            <p className="numeric mt-1 text-[17px] leading-none font-semibold text-ink">{vendor.orders_completed}</p>
          </div>
          <div className={clsx("rounded-md p-3", vendor.disputes > 0 ? "bg-warning-dim" : "bg-surface-2")}>
            <p className="eyebrow">Disputes</p>
            <p
              className={clsx(
                "numeric mt-1 text-[17px] leading-none font-semibold",
                vendor.disputes > 0 ? "text-warning" : "text-ink"
              )}
            >
              {vendor.disputes}
            </p>
          </div>
        </div>

        {isPending && (
          <div className="space-y-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-32" />
          </div>
        )}

        {noContextYet && (
          <p className="rounded-md bg-surface-2 px-4 py-3 text-[13px] leading-relaxed text-ink-muted">
            No negotiation context for this vendor yet. The briefing, last agreed terms and guardrails appear here once
            an agent has worked a disruption with them.
          </p>
        )}

        {error && !noContextYet && (
          <p className="rounded-md bg-critical-dim px-4 py-3 text-[13px] text-critical">
            Couldn&apos;t load this vendor&apos;s negotiation context. The figures above come from the vendor list and
            are unaffected.
          </p>
        )}

        {context && (
          <>
            <DetailBlock title="What the agent says about them">
              <p className="text-[14px] leading-relaxed text-ink">“{context.briefing}”</p>
              {context.history_summary && (
                <p className="mt-3 border-t border-line pt-3 text-[12.5px] leading-relaxed text-ink-muted">
                  {context.history_summary}
                </p>
              )}
              <p className="mt-3 text-[11px] text-ink-faint">{MEMORY_NOTE[context.memory_source]}</p>
            </DetailBlock>

            <div className="grid gap-3 sm:grid-cols-2">
              <DetailBlock title="Last agreed terms">
                {context.last_terms ? (
                  <div className="grid grid-cols-2 gap-3">
                    <DetailField label="Unit price">
                      <span className="numeric">{formatUnitPrice(context.last_terms.unit_price_paise)}</span>
                    </DetailField>
                    <DetailField label="Lead time">
                      <span className="numeric">{context.last_terms.lead_time_days}</span> days
                    </DetailField>
                    <DetailField label="Payment terms">
                      <span className="numeric">{context.last_terms.payment_terms_days}</span> days
                    </DetailField>
                    <DetailField label="Agreed">
                      <span className="numeric">{formatDate(context.last_terms.agreed_at)}</span>
                      <span className="block text-[11px] text-ink-faint">
                        {formatTimeAgo(context.last_terms.agreed_at)}
                      </span>
                    </DetailField>
                  </div>
                ) : (
                  <p className="text-[13px] text-ink-faint">Nothing negotiated with them yet.</p>
                )}
              </DetailBlock>

              <DetailBlock title="Guardrails on this vendor">
                <div className="grid grid-cols-2 gap-3">
                  <DetailField label="Max unit price">
                    <span className="numeric">{formatUnitPrice(context.guardrails.max_unit_price_paise)}</span>
                  </DetailField>
                  <DetailField label="Max lead time">
                    <span className="numeric">{context.guardrails.max_lead_time_days}</span> days
                  </DetailField>
                  <DetailField label="Needs your approval above">
                    <span className="numeric">{formatCeiling(context.guardrails.requires_human_above_paise)}</span>
                  </DetailField>
                </div>
              </DetailBlock>
            </div>
          </>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <DetailBlock title="Outstanding">
            {vendor.dues_paise > 0 ? (
              <div className="grid grid-cols-2 gap-3">
                <DetailField label="Owed">
                  <span className="numeric font-semibold">{vendor.dues_display}</span>
                </DetailField>
                {due && (
                  <>
                    <DetailField label="Invoices">
                      <span className="numeric">{due.invoice_count}</span>
                    </DetailField>
                    <DetailField label="Oldest invoice">
                      <span className="numeric">{due.oldest_invoice_age_days}</span> days old
                    </DetailField>
                  </>
                )}
              </div>
            ) : (
              <p className="text-[13px] text-ink-faint">Nothing owed.</p>
            )}
          </DetailBlock>

          <DetailBlock title="Contact & identity">
            <div className="grid grid-cols-2 gap-3">
              <DetailField label="Phone">
                <span className="numeric">{vendor.phone}</span>
              </DetailField>
              <DetailField label="Speaks">{vendor.languages.map(languageLabel).join(", ") || "—"}</DetailField>
              <DetailField label="GSTIN">
                <span className="numeric text-[12px]">{vendor.gstin}</span>
              </DetailField>
              <DetailField label="Udyam">
                <span className="numeric text-[12px]">{vendor.udyam_number ?? "Not registered"}</span>
              </DetailField>
            </div>
          </DetailBlock>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---- Tab 1: My vendors ----------------------------------------------------

function MyVendorRow({ vendor, onOpen }: { vendor: Vendor; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={clsx(ROW_GRID, "row-hover w-full py-3.5 text-left outline-offset-[-2px]")}
    >
      <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 lg:col-span-1">
        <span className="truncate text-[13.5px] font-medium text-ink">{vendor.name}</span>
        {vendor.disputes > 0 && <DisputeChip count={vendor.disputes} />}
        <span className="w-full truncate text-[11.5px] text-ink-faint">{vendor.category}</span>
      </div>

      <span className="inline-flex min-w-0 items-center gap-1.5 text-[12.5px] text-ink-muted">
        <MapPin size={13} className="shrink-0 text-ink-faint" />
        <span className="truncate">
          {vendor.city}, {vendor.state}
        </span>
      </span>

      <ReliabilityMeter score={vendor.reliability_score_0_100} />

      <span className="text-[12.5px] text-ink-muted">
        <span className="numeric">{Math.round(vendor.on_time_rate * 100)}%</span> on time
        <span className="block text-[11.5px] text-ink-faint">
          <span className="numeric">{vendor.orders_completed}</span> orders
        </span>
      </span>

      <span
        className={clsx(
          "numeric text-right text-[13px]",
          vendor.dues_paise > 0 ? "font-semibold text-ink" : "text-ink-faint"
        )}
      >
        {vendor.dues_paise > 0 ? vendor.dues_display : "—"}
      </span>
    </button>
  );
}

function MyVendorsPanel() {
  const [searchInput, setSearchInput] = useState("");
  const search = useDebounced(searchInput.trim(), 250);
  const [selected, setSelected] = useState<Vendor | null>(null);

  // The summary describes the whole vendor book, so it reads off the
  // unfiltered query and stays still while you type. With an empty search the
  // two calls share a query key, so this is one request, not two.
  const book = useVendors();
  const list = useVendors(search || undefined);
  const dues = useVendorDues();

  const allVendors = book.data?.items ?? [];
  const vendors = list.data?.items ?? [];
  const withDues = allVendors.filter((v) => v.dues_paise > 0);
  const duesTotalPaise = withDues.reduce((sum, v) => sum + v.dues_paise, 0);

  const dueByVendor = useMemo(() => {
    const map = new Map<string, VendorDue>();
    for (const item of dues.data?.items ?? []) map.set(item.vendor.id, item);
    return map;
  }, [dues.data]);

  const searching = search.length > 0;

  return (
    <div>
      {book.isPending && <Skeleton className="mb-4 h-[70px]" />}
      {book.data && (
        <div className="panel mb-4 flex flex-wrap items-center gap-x-10 gap-y-4 px-5 py-3.5">
          <SummaryStat label="Vendors you trade with" value={String(book.data.total)} />
          <SummaryStat label="With outstanding dues" value={String(withDues.length)} />
          <SummaryStat
            label="Total outstanding"
            value={formatPaiseFull(duesTotalPaise)}
            tone={duesTotalPaise > 0 ? "alert" : "default"}
          />
        </div>
      )}

      <div className="panel mb-3 flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
        <div className="relative min-w-0 flex-1 sm:max-w-xs">
          <Search size={14} className="absolute top-1/2 left-3 -translate-y-1/2 text-ink-faint" />
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Filter by name, category, city…"
            aria-label="Filter your vendors"
            className={clsx(FIELD, "w-full pr-8 pl-9")}
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => setSearchInput("")}
              aria-label="Clear filter"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm p-1 text-ink-faint transition-colors duration-200 hover:text-ink"
            >
              <X size={13} />
            </button>
          )}
        </div>

        <span className="text-[12.5px] text-ink-muted">
          {list.isPending && "Loading…"}
          {list.data &&
            (searching ? (
              <>
                <span className="numeric">{list.data.total}</span> of{" "}
                <span className="numeric">{book.data?.total ?? allVendors.length}</span> vendors
              </>
            ) : (
              <>
                <span className="numeric">{list.data.total}</span> vendors
              </>
            ))}
        </span>
      </div>

      {list.isPending ? (
        <div className="panel-flush">
          <ColumnHeader
            columns={[
              { label: "Vendor" },
              { label: "Location" },
              { label: "Reliability" },
              { label: "Track record" },
              { label: "Dues", align: "right" },
            ]}
          />
          <RowSkeletons />
        </div>
      ) : list.isError ? (
        <EmptyBlock icon={AlertTriangle} title="Couldn't load your vendors">
          The vendor service didn&apos;t answer. Nothing here is missing — it just hasn&apos;t arrived. Reload to try
          again.
        </EmptyBlock>
      ) : vendors.length === 0 ? (
        searching ? (
          <EmptyBlock icon={Search} title={`Nothing matches “${search}”`}>
            No vendor in your book matches that. Clear the filter to see all{" "}
            <span className="numeric">{book.data?.total ?? allVendors.length}</span> of them, or look for someone new
            under Discover.
          </EmptyBlock>
        ) : (
          <EmptyBlock icon={Building2} title="No vendors on your books yet">
            Vendors appear here once your purchase history is in. Import it from{" "}
            <Link
              href="/onboarding"
              className="rounded-sm font-medium text-accent underline underline-offset-2 transition-colors duration-200 hover:text-accent-bright"
            >
              Data sources
            </Link>
            , or find someone new under Discover.
          </EmptyBlock>
        )
      ) : (
        <div className="panel-flush">
          <ColumnHeader
            columns={[
              { label: "Vendor" },
              { label: "Location" },
              { label: "Reliability" },
              { label: "Track record" },
              { label: "Dues", align: "right" },
            ]}
          />
          <div className="divide-y divide-line">
            {vendors.map((vendor) => (
              <MyVendorRow key={vendor.id} vendor={vendor} onOpen={() => setSelected(vendor)} />
            ))}
          </div>
        </div>
      )}

      {selected && (
        <VendorDetailDialog
          vendor={selected}
          due={dueByVendor.get(selected.id)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}

// ---- Tab 2: Discover ------------------------------------------------------

function DiscoverRow({ vendor }: { vendor: PublicVendor }) {
  return (
    <Link
      href={`/directory/${vendor.id}`}
      className={clsx(ROW_GRID, "row-hover py-3.5 outline-offset-[-2px]")}
    >
      <div className="col-span-2 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 lg:col-span-1">
        <span className="truncate text-[13.5px] font-medium text-ink">{vendor.name}</span>
        <VerificationBadge verified={vendor.verified} gstinVerified={vendor.gstin_verified} size="sm" />
        <span className="w-full truncate text-[11.5px] text-ink-faint">{vendor.category}</span>
      </div>

      <span className="inline-flex min-w-0 items-center gap-1.5 text-[12.5px] text-ink-muted">
        <MapPin size={13} className="shrink-0 text-ink-faint" />
        <span className="truncate">
          {vendor.city}, {vendor.state}
          {vendor.distance_km !== null && (
            <span className="numeric text-ink-faint"> · {vendor.distance_km.toFixed(0)} km</span>
          )}
        </span>
      </span>

      <ReliabilityMeter score={vendor.reliability_score_0_100} />

      <span className="text-[12.5px] text-ink-muted">
        <span className="numeric">{vendor.lead_time_days}</span>-day lead
        <span className="block text-[11.5px] text-ink-faint">
          <span className="numeric">{vendor.capacity_units_per_month.toLocaleString("en-IN")}</span> units/mo
        </span>
      </span>

      <span className="flex justify-start lg:justify-end">
        <LanguagePills codes={vendor.languages} />
      </span>
    </Link>
  );
}

function DiscoverPanel() {
  const [category, setCategory] = useState("");
  const [language, setLanguage] = useState("");
  // Off by default for the same reason /directory leaves it off: "verified"
  // needs Udyam, which needs a live provider this deployment doesn't have, so
  // defaulting it on renders an empty pool. Every row still shows its own
  // honest badge.
  const [verifiedOnly, setVerifiedOnly] = useState(false);

  const params: PublicVendorSearchParams = {
    category: category || undefined,
    languages: language ? [language] : undefined,
    verified: verifiedOnly ? true : undefined,
  };

  // The filter options are derived from the unfiltered pool rather than a
  // hardcoded list, so a newly registered category can't go missing from the
  // dropdown. Same query key as the filtered call when nothing is set.
  const pool = usePublicVendors({});
  const { data, isPending, isError } = usePublicVendors(params);

  const categories = useMemo(
    () => [...new Set((pool.data?.items ?? []).map((v) => v.category))].sort(),
    [pool.data]
  );
  const languages = useMemo(
    () => [...new Set((pool.data?.items ?? []).flatMap((v) => v.languages))].sort(),
    [pool.data]
  );

  const vendors = data?.items ?? [];
  const filtered = Boolean(category || language || verifiedOnly);

  return (
    <div>
      <div className="panel mb-3 flex flex-wrap items-center justify-between gap-3 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            aria-label="Filter by category"
            className={clsx(FIELD, "max-w-[15rem]")}
          >
            <option value="">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            aria-label="Filter by language"
            className={FIELD}
          >
            <option value="">Any language</option>
            {languages.map((code) => (
              <option key={code} value={code}>
                {languageLabel(code)}
              </option>
            ))}
          </select>

          <label className="flex h-9 cursor-pointer items-center gap-2 rounded-md px-1 text-[13px] font-medium text-ink-muted transition-colors duration-200 hover:text-ink">
            <input
              type="checkbox"
              checked={verifiedOnly}
              onChange={(e) => setVerifiedOnly(e.target.checked)}
              className="size-4 rounded-sm border-line-strong accent-accent"
            />
            Verified only
          </label>
        </div>

        <span className="text-[12.5px] text-ink-muted">
          {isPending && "Searching…"}
          {data && (
            <>
              <span className="numeric">{data.total}</span> listed
            </>
          )}
        </span>
      </div>

      {isPending ? (
        <div className="panel-flush">
          <ColumnHeader
            columns={[
              { label: "Vendor" },
              { label: "Location" },
              { label: "Reliability" },
              { label: "Capacity" },
              { label: "Languages", align: "right" },
            ]}
          />
          <RowSkeletons count={5} />
        </div>
      ) : isError ? (
        <EmptyBlock icon={AlertTriangle} title="Couldn't reach the directory">
          The public vendor directory didn&apos;t answer. Reload to try again — your own vendors are unaffected.
        </EmptyBlock>
      ) : vendors.length === 0 ? (
        <EmptyBlock icon={PackageSearch} title={filtered ? "No listings match these filters" : "Nothing listed yet"}>
          This directory only carries vendors who&apos;ve self-registered and passed the GSTIN and Udyam checks
          {filtered ? " — try widening the filters, or " : " — "}
          <Link
            href="/directory/register"
            className="rounded-sm font-medium text-accent underline underline-offset-2 transition-colors duration-200 hover:text-accent-bright"
          >
            invite a vendor to list themselves
          </Link>
          .
        </EmptyBlock>
      ) : (
        <>
          <div className="panel-flush">
            <ColumnHeader
              columns={[
                { label: "Vendor" },
                { label: "Location" },
                { label: "Reliability" },
                { label: "Capacity" },
                { label: "Languages", align: "right" },
              ]}
            />
            <div className="divide-y divide-line">
              {vendors.map((vendor) => (
                <DiscoverRow key={vendor.id} vendor={vendor} />
              ))}
            </div>
          </div>

          <p className="mt-3 text-[12.5px] text-ink-muted">
            Buying from someone who isn&apos;t here?{" "}
            <Link
              href="/directory/register"
              className="rounded-sm font-medium text-accent underline underline-offset-2 transition-colors duration-200 hover:text-accent-bright"
            >
              Invite a vendor to list themselves
            </Link>
            .
          </p>
        </>
      )}
    </div>
  );
}

export default function VendorsPage() {
  return (
    <div>
      <PageHeader
        title="Vendors"
        subtitle="Everyone you currently buy from, with the reliability and money position behind each name — and a directory of verified suppliers when you need a second source."
      />

      {/* Panels unmount when inactive, which costs the other tab's filter
          state on a switch — accepted so that opening this page doesn't also
          query the public directory you may never look at. React Query still
          holds the rows, so coming back is instant. */}
      <Tabs defaultValue="mine">
        <TabsList>
          <TabsTrigger value="mine">
            <Building2 />
            My vendors
          </TabsTrigger>
          <TabsTrigger value="discover">
            <Compass />
            Discover
          </TabsTrigger>
        </TabsList>

        <TabsContent value="mine">
          <MyVendorsPanel />
        </TabsContent>
        <TabsContent value="discover">
          <DiscoverPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
