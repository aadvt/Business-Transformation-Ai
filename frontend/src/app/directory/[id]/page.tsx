"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { Building2, Check, Clock, Gauge, Globe2, MapPin, Package, X } from "lucide-react";
import { usePublicVendor } from "@/lib/queries";
import { resolveStateCode } from "@/lib/gstin";
import VerificationBadge from "@/components/VerificationBadge";
import type { VerificationEvidence } from "@/lib/types";

const LANGUAGE_LABEL: Record<string, string> = { hi: "Hindi", mr: "Marathi", en: "English", ta: "Tamil", te: "Telugu", gu: "Gujarati", kn: "Kannada" };

function EvidenceRow({ pass, label, detail }: { pass: boolean; label: string; detail: string }) {
  return (
    <div className="flex items-start gap-3 border-b border-slate-100 py-3 last:border-b-0">
      <span
        className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full ${
          pass ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
        }`}
      >
        {pass ? <Check size={12} /> : <X size={12} />}
      </span>
      <div>
        <p className="text-[13.5px] font-medium text-slate-800">{label}</p>
        <p className="text-[12.5px] text-slate-500">{detail}</p>
      </div>
    </div>
  );
}

function evidenceRows(v: VerificationEvidence) {
  const stateName = resolveStateCode(v.state_code);
  return [
    { pass: v.gstin_structure_valid, label: "GSTIN structure", detail: "2-digit state code + 10-char PAN + entity code + 'Z' + checksum" },
    { pass: v.gstin_checksum_valid, label: "GSTIN checksum", detail: "Mod-36 check digit recomputed and matched against the registered GSTIN" },
    {
      pass: v.state_code_resolved,
      label: "State code resolved",
      detail: v.state_code ? `${v.state_code}${stateName ? ` → ${stateName}` : " — not in our state code table"}` : "No state code to resolve",
    },
    { pass: v.udyam_format_valid, label: "Udyam format", detail: "UDYAM-XX-YY-NNNNNNN shape, if a Udyam number was supplied" },
  ];
}

export default function VendorDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: vendor, isLoading, error } = usePublicVendor(params.id);

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-xl border border-slate-200 bg-white" />;
  }

  if (error || !vendor) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
        <p className="text-[14px] font-medium text-slate-700">Vendor not found</p>
        <Link href="/directory" className="mt-2 inline-block text-[13px] font-medium text-slate-900 underline underline-offset-2">
          Back to search
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link href="/directory" className="mb-4 inline-block text-[13px] font-medium text-slate-500 hover:text-slate-900">
        ← Back to search
      </Link>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-slate-200 bg-white p-5">
        <div>
          <div className="mb-1.5 flex items-center gap-2.5">
            <h1 className="text-[20px] font-semibold tracking-tight text-slate-900">{vendor.name}</h1>
            <VerificationBadge verified={vendor.verified} />
          </div>
          <p className="text-[13.5px] text-slate-500">{vendor.category}</p>
          <p className="mt-2 flex items-center gap-1 text-[13px] text-slate-500">
            <MapPin size={13} />
            {vendor.city}, {vendor.state} {vendor.pincode}
          </p>
        </div>
        <span className="font-mono text-[13px] text-slate-400">{vendor.gstin_masked}</span>
      </div>

      {/* The hero: verification evidence, shown as its own checked rows rather
          than collapsed into one badge — the whole point is showing the work. */}
      <div className="mb-6 rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="mb-1 text-[15px] font-semibold text-slate-900">Verification evidence</h2>
        <p className="mb-3 text-[12.5px] text-slate-500">
          {vendor.verification.source} · checked {new Date(vendor.verification.checked_at).toLocaleString()}
        </p>
        <div>
          {evidenceRows(vendor.verification).map((row) => (
            <EvidenceRow key={row.label} {...row} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-[15px] font-semibold text-slate-900">Reliability</h2>
          <div className="mb-3 flex items-center gap-3">
            <span className="text-[28px] font-semibold tracking-tight text-slate-900">{vendor.reliability.score_0_100}</span>
            <span className="text-[13px] text-slate-500">/ 100</span>
          </div>
          <dl className="space-y-1.5 text-[13px]">
            <div className="flex justify-between">
              <dt className="text-slate-500">On-time rate</dt>
              <dd className="font-medium text-slate-800">{Math.round(vendor.reliability.on_time_rate * 100)}%</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Orders completed</dt>
              <dd className="font-medium text-slate-800">{vendor.orders_completed}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Disputes</dt>
              <dd className="font-medium text-slate-800">{vendor.reliability.disputes}</dd>
            </div>
          </dl>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-[15px] font-semibold text-slate-900">Capacity &amp; reach</h2>
          <dl className="space-y-2.5 text-[13px]">
            <div className="flex items-center justify-between">
              <dt className="flex items-center gap-1.5 text-slate-500">
                <Clock size={13} /> Lead time
              </dt>
              <dd className="font-medium text-slate-800">{vendor.lead_time_days} days</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="flex items-center gap-1.5 text-slate-500">
                <Package size={13} /> Capacity
              </dt>
              <dd className="font-medium text-slate-800">{vendor.capacity_units_per_month.toLocaleString("en-IN")} units/mo</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="flex items-center gap-1.5 text-slate-500">
                <Building2 size={13} /> Distance
              </dt>
              <dd className="font-medium text-slate-800">{vendor.distance_km !== null ? `${vendor.distance_km.toFixed(0)} km` : "—"}</dd>
            </div>
            <div className="flex items-start justify-between">
              <dt className="flex items-center gap-1.5 text-slate-500">
                <Globe2 size={13} /> Languages
              </dt>
              <dd className="flex flex-wrap justify-end gap-1">
                {vendor.languages.map((l) => (
                  <span key={l} className="rounded-sm bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-600">
                    {LANGUAGE_LABEL[l] ?? l}
                  </span>
                ))}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-1.5 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-3 text-[12.5px] text-slate-500">
        <Gauge size={13} />
        Sourced automatically as a candidate for compatible disruptions once verified — see the candidate rail in the
        ops console.
      </div>
    </div>
  );
}
