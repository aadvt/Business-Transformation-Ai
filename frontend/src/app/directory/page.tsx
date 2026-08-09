"use client";

import { useState } from "react";
import Link from "next/link";
import { MapPin, Clock, Star, Search as SearchIcon } from "lucide-react";
import { usePublicVendors } from "@/lib/queries";
import VerificationBadge from "@/components/VerificationBadge";
import type { PublicVendor, PublicVendorSearchParams } from "@/lib/types";

const CATEGORIES = [
  "Automotive Fasteners",
  "CNC Machined Parts",
  "Raw Steel Coil",
  "Electrical Wiring & Harnesses",
  "Jig & Fixture Tooling",
];

const LANGUAGES: { code: string; label: string }[] = [
  { code: "hi", label: "Hindi" },
  { code: "mr", label: "Marathi" },
  { code: "en", label: "English" },
  { code: "ta", label: "Tamil" },
  { code: "te", label: "Telugu" },
  { code: "gu", label: "Gujarati" },
];

const FIELD_CLASS =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink transition-colors duration-200 placeholder:text-ink-faint hover:border-line-strong focus:border-accent";

const FIELD_LABEL = "mb-1.5 block text-[12.5px] font-medium text-ink-muted";

function VendorCard({ vendor }: { vendor: PublicVendor }) {
  return (
    <Link
      href={`/directory/${vendor.id}`}
      className="panel panel-interactive block p-5 outline-offset-2"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-[15px] font-bold tracking-[-0.01em] text-ink">{vendor.name}</p>
          <p className="text-[12.5px] text-ink-muted">{vendor.category}</p>
        </div>
        <VerificationBadge verified={vendor.verified} gstinVerified={vendor.gstin_verified} />
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12.5px] text-ink-muted">
        <span className="inline-flex items-center gap-1.5">
          <MapPin size={13} className="text-ink-faint" />
          {vendor.city}, {vendor.state}
          {vendor.distance_km !== null && (
            <>
              {" · "}
              <span className="numeric">{vendor.distance_km.toFixed(0)} km</span>
            </>
          )}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Clock size={13} className="text-ink-faint" />
          <span className="numeric">{vendor.lead_time_days}</span>-day lead time
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Star size={13} className="text-ink-faint" />
          <span className="numeric">{vendor.reliability_score_0_100}/100</span> reliability
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
        <div className="flex flex-wrap gap-1.5">
          {vendor.languages.map((l) => (
            <span
              key={l}
              className="rounded-full bg-surface-3 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-ink-muted uppercase"
            >
              {l}
            </span>
          ))}
        </div>
        <span className="numeric text-[11px] text-ink-faint">{vendor.gstin_masked}</span>
      </div>
    </Link>
  );
}

export default function DirectorySearchPage() {
  const [category, setCategory] = useState("");
  const [pincode, setPincode] = useState("");
  const [radiusKm, setRadiusKm] = useState("");
  const [maxLeadTime, setMaxLeadTime] = useState("");
  const [minCapacity, setMinCapacity] = useState("");
  const [languages, setLanguages] = useState<string[]>([]);
  // Off by default: "verified" means GSTIN *and* Udyam passed, and Udyam
  // needs a live provider we don't have configured — so defaulting this on
  // renders an empty directory. Every card still shows its own honest badge
  // and per-check evidence, so nothing is overclaimed by listing them.
  const [verifiedOnly, setVerifiedOnly] = useState(false);

  const params: PublicVendorSearchParams = {
    category: category || undefined,
    pincode: pincode || undefined,
    radius_km: radiusKm ? Number(radiusKm) : undefined,
    max_lead_time_days: maxLeadTime ? Number(maxLeadTime) : undefined,
    min_capacity: minCapacity ? Number(minCapacity) : undefined,
    languages: languages.length > 0 ? languages : undefined,
    verified: verifiedOnly ? true : undefined,
  };

  const { data, isLoading } = usePublicVendors(params);

  function toggleLanguage(code: string) {
    setLanguages((prev) => (prev.includes(code) ? prev.filter((l) => l !== code) : [...prev, code]));
  }

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[248px_minmax(0,1fr)]">
      <aside className="panel h-fit p-5">
        <h2 className="eyebrow mb-4">Filters</h2>

        <div className="mb-4">
          <label className={FIELD_LABEL}>Category</label>
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={FIELD_CLASS}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        <div className="mb-4 flex gap-2">
          <div className="flex-1">
            <label className={FIELD_LABEL}>Pincode</label>
            <input
              value={pincode}
              onChange={(e) => setPincode(e.target.value)}
              placeholder="411001"
              className={`${FIELD_CLASS} numeric`}
            />
          </div>
          <div className="w-20">
            <label className={FIELD_LABEL}>Radius</label>
            <input
              type="number"
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
              placeholder="km"
              className={`${FIELD_CLASS} numeric`}
            />
          </div>
        </div>

        <div className="mb-4">
          <label className={FIELD_LABEL}>Max lead time (days)</label>
          <input
            type="number"
            value={maxLeadTime}
            onChange={(e) => setMaxLeadTime(e.target.value)}
            className={`${FIELD_CLASS} numeric`}
          />
        </div>

        <div className="mb-4">
          <label className={FIELD_LABEL}>Min capacity (units/mo)</label>
          <input
            type="number"
            value={minCapacity}
            onChange={(e) => setMinCapacity(e.target.value)}
            className={`${FIELD_CLASS} numeric`}
          />
        </div>

        <div className="mb-4">
          <label className={FIELD_LABEL}>Languages</label>
          <div className="flex flex-wrap gap-1.5">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                type="button"
                onClick={() => toggleLanguage(l.code)}
                aria-pressed={languages.includes(l.code)}
                className={`rounded-full px-3 py-1.5 text-[11.5px] font-medium outline-offset-2 transition-colors duration-200 ${
                  languages.includes(l.code)
                    ? "bg-accent text-accent-ink hover:bg-accent-bright"
                    : "bg-surface-2 text-ink-muted hover:bg-surface-3 hover:text-ink"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex cursor-pointer items-center gap-2 rounded-sm text-[13px] font-medium text-ink-muted transition-colors duration-200 hover:text-ink">
          <input
            type="checkbox"
            checked={verifiedOnly}
            onChange={(e) => setVerifiedOnly(e.target.checked)}
            className="size-4 rounded-sm border-line-strong accent-accent"
          />
          Verified only
        </label>
      </aside>

      <section>
        <div className="mb-5 flex items-center justify-between gap-3">
          <h1 className="font-display text-[30px] leading-[1.15] font-bold tracking-[-0.02em] text-ink">
            Find a vendor
          </h1>
          <span className="text-[13px] text-ink-muted">
            {isLoading ? "Searching…" : <><span className="numeric">{data?.total ?? 0}</span> vendors</>}
          </span>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="skeleton h-36 rounded-lg" />
            ))}
          </div>
        ) : (data?.items.length ?? 0) === 0 ? (
          <div className="rounded-lg border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
            <span className="mx-auto mb-4 flex size-11 items-center justify-center rounded-md bg-surface-3 text-ink-faint">
              <SearchIcon size={20} />
            </span>
            <p className="font-display mb-1.5 text-[15px] font-bold text-ink">No vendors match these filters yet</p>
            <p className="mx-auto max-w-sm text-[13px] leading-relaxed text-ink-muted">
              This directory only lists vendors who&apos;ve self-registered and passed our GSTIN + Udyam checks —
              try widening your filters, or{" "}
              <Link
                href="/directory/register"
                className="rounded-sm font-medium text-accent underline underline-offset-2 outline-offset-2 transition-colors duration-200 hover:text-accent-bright"
              >
                invite a vendor to list themselves
              </Link>
              .
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {data!.items.map((vendor) => (
              <VendorCard key={vendor.id} vendor={vendor} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
