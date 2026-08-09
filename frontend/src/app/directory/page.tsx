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

function VendorCard({ vendor }: { vendor: PublicVendor }) {
  return (
    <Link
      href={`/directory/${vendor.id}`}
      className="block rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div>
          <p className="text-[14px] font-semibold text-slate-900">{vendor.name}</p>
          <p className="text-[12.5px] text-slate-500">{vendor.category}</p>
        </div>
        <VerificationBadge verified={vendor.verified} />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-slate-500">
        <span className="inline-flex items-center gap-1">
          <MapPin size={12} />
          {vendor.city}, {vendor.state}
          {vendor.distance_km !== null && ` · ${vendor.distance_km.toFixed(0)} km`}
        </span>
        <span className="inline-flex items-center gap-1">
          <Clock size={12} />
          {vendor.lead_time_days}-day lead time
        </span>
        <span className="inline-flex items-center gap-1">
          <Star size={12} />
          {vendor.reliability_score_0_100}/100 reliability
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2.5">
        <div className="flex flex-wrap gap-1">
          {vendor.languages.map((l) => (
            <span key={l} className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 uppercase">
              {l}
            </span>
          ))}
        </div>
        <span className="font-mono text-[11px] text-slate-400">{vendor.gstin_masked}</span>
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
  const [verifiedOnly, setVerifiedOnly] = useState(true);

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
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[240px_minmax(0,1fr)]">
      <aside className="h-fit rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-[12px] font-semibold tracking-wide text-slate-400 uppercase">Filters</h2>

        <div className="mb-4">
          <label className="mb-1 block text-[12.5px] font-medium text-slate-700">Category</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400"
          >
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
            <label className="mb-1 block text-[12.5px] font-medium text-slate-700">Pincode</label>
            <input
              value={pincode}
              onChange={(e) => setPincode(e.target.value)}
              placeholder="411001"
              className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400"
            />
          </div>
          <div className="w-20">
            <label className="mb-1 block text-[12.5px] font-medium text-slate-700">Radius</label>
            <input
              type="number"
              value={radiusKm}
              onChange={(e) => setRadiusKm(e.target.value)}
              placeholder="km"
              className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400"
            />
          </div>
        </div>

        <div className="mb-4">
          <label className="mb-1 block text-[12.5px] font-medium text-slate-700">Max lead time (days)</label>
          <input
            type="number"
            value={maxLeadTime}
            onChange={(e) => setMaxLeadTime(e.target.value)}
            className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400"
          />
        </div>

        <div className="mb-4">
          <label className="mb-1 block text-[12.5px] font-medium text-slate-700">Min capacity (units/mo)</label>
          <input
            type="number"
            value={minCapacity}
            onChange={(e) => setMinCapacity(e.target.value)}
            className="w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 outline-none focus:border-slate-400"
          />
        </div>

        <div className="mb-4">
          <label className="mb-1.5 block text-[12.5px] font-medium text-slate-700">Languages</label>
          <div className="flex flex-wrap gap-1.5">
            {LANGUAGES.map((l) => (
              <button
                key={l.code}
                type="button"
                onClick={() => toggleLanguage(l.code)}
                className={`rounded-full border px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                  languages.includes(l.code)
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-600 hover:border-slate-400"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[13px] font-medium text-slate-700">
          <input
            type="checkbox"
            checked={verifiedOnly}
            onChange={(e) => setVerifiedOnly(e.target.checked)}
            className="size-4 rounded border-slate-300 accent-slate-900"
          />
          Verified only
        </label>
      </aside>

      <section>
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-[19px] font-semibold tracking-tight text-slate-900">Find a vendor</h1>
          <span className="text-[13px] text-slate-500">{isLoading ? "Searching…" : `${data?.total ?? 0} vendors`}</span>
        </div>

        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-32 animate-pulse rounded-xl border border-slate-200 bg-white" />
            ))}
          </div>
        ) : (data?.items.length ?? 0) === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
            <SearchIcon size={22} className="mx-auto mb-3 text-slate-300" />
            <p className="mb-1 text-[14px] font-medium text-slate-700">No vendors match these filters yet</p>
            <p className="mx-auto max-w-sm text-[13px] text-slate-500">
              This directory only lists vendors who&apos;ve self-registered and passed our GSTIN + Udyam checks —
              try widening your filters, or{" "}
              <Link href="/directory/register" className="font-medium text-slate-900 underline underline-offset-2">
                invite a vendor to list themselves
              </Link>
              .
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {data!.items.map((vendor) => (
              <VendorCard key={vendor.id} vendor={vendor} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
