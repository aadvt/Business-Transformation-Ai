"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Building2, Check, Clock, Gauge, Globe2, MapPin, Package, X } from "lucide-react";
import { usePublicVendor } from "@/lib/queries";
import { resolveStateCode } from "@/lib/gstin";
import VerificationBadge from "@/components/VerificationBadge";
import type { VerificationEvidence } from "@/lib/types";

const LANGUAGE_LABEL: Record<string, string> = { hi: "Hindi", mr: "Marathi", en: "English", ta: "Tamil", te: "Telugu", gu: "Gujarati", kn: "Kannada" };

function EvidenceRow({ pass, label, detail }: { pass: boolean; label: string; detail: string }) {
  return (
    <div className="flex items-start gap-3 border-b border-line py-3.5 last:border-b-0">
      <span
        className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full ${
          pass ? "bg-success-dim text-success" : "bg-critical-dim text-critical"
        }`}
      >
        {pass ? <Check size={12} /> : <X size={12} />}
      </span>
      <div>
        <p className="text-[13.5px] font-medium text-ink">{label}</p>
        <p className="text-[12.5px] text-ink-muted">{detail}</p>
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

const STAT_LABEL = "flex items-center gap-2 text-ink-muted";
const STAT_VALUE = "numeric font-medium text-ink";

export default function VendorDetailPage() {
  const params = useParams<{ id: string }>();
  const { data: vendor, isLoading, error } = usePublicVendor(params.id);

  if (isLoading) {
    return <div className="skeleton h-64 rounded-lg" />;
  }

  if (error || !vendor) {
    return (
      <div className="rounded-lg border border-dashed border-line-strong bg-surface px-6 py-12 text-center">
        <p className="font-display text-[15px] font-bold text-ink">Vendor not found</p>
        <Link
          href="/directory"
          className="mt-2 inline-block rounded-sm text-[13px] font-medium text-accent underline underline-offset-2 outline-offset-2 transition-colors duration-200 hover:text-accent-bright"
        >
          Back to search
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link
        href="/directory"
        className="mb-4 inline-flex items-center gap-1.5 rounded-md px-1 py-1 text-[13px] font-medium text-ink-muted outline-offset-2 transition-colors duration-200 hover:text-ink"
      >
        <ArrowLeft size={14} />
        Back to search
      </Link>

      <div className="panel mb-6 flex flex-wrap items-start justify-between gap-4 p-6">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-3">
            <h1 className="font-display text-[30px] leading-[1.15] font-bold tracking-[-0.02em] text-ink">
              {vendor.name}
            </h1>
            <VerificationBadge
              verified={vendor.verified}
              gstinVerified={vendor.verification.gstin_structure_valid && vendor.verification.gstin_checksum_valid}
            />
          </div>
          <p className="text-[13.5px] text-ink-muted">{vendor.category}</p>
          <p className="mt-2 flex items-center gap-1.5 text-[13px] text-ink-muted">
            <MapPin size={13} className="text-ink-faint" />
            {vendor.city}, {vendor.state} <span className="numeric">{vendor.pincode}</span>
          </p>
        </div>
        <span className="numeric text-[13px] text-ink-faint">{vendor.gstin_masked}</span>
      </div>

      {/* The hero: verification evidence, shown as its own checked rows rather
          than collapsed into one badge — the whole point is showing the work. */}
      <div className="panel mb-6 p-6">
        <h2 className="font-display mb-1 text-[17px] font-bold tracking-[-0.01em] text-ink">Verification evidence</h2>
        <p className="mb-2 text-[12.5px] text-ink-muted">
          {vendor.verification.source} · checked {new Date(vendor.verification.checked_at).toLocaleString()}
        </p>
        <div>
          {evidenceRows(vendor.verification).map((row) => (
            <EvidenceRow key={row.label} {...row} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="panel p-6">
          <h2 className="font-display mb-4 text-[17px] font-bold tracking-[-0.01em] text-ink">Reliability</h2>
          <div className="mb-4 flex items-baseline gap-2">
            <span className="numeric text-[36px] leading-none font-semibold text-ink">
              {vendor.reliability.score_0_100}
            </span>
            <span className="text-[13px] text-ink-faint">/ 100</span>
          </div>
          <dl className="space-y-2.5 text-[13px]">
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-muted">On-time rate</dt>
              <dd className={STAT_VALUE}>{Math.round(vendor.reliability.on_time_rate * 100)}%</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-muted">Orders completed</dt>
              <dd className={STAT_VALUE}>{vendor.orders_completed}</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-ink-muted">Disputes</dt>
              <dd className={STAT_VALUE}>{vendor.reliability.disputes}</dd>
            </div>
          </dl>
        </div>

        <div className="panel p-6">
          <h2 className="font-display mb-4 text-[17px] font-bold tracking-[-0.01em] text-ink">Capacity &amp; reach</h2>
          <dl className="space-y-2.5 text-[13px]">
            <div className="flex items-center justify-between gap-3">
              <dt className={STAT_LABEL}>
                <Clock size={13} className="text-ink-faint" /> Lead time
              </dt>
              <dd className={STAT_VALUE}>{vendor.lead_time_days} days</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className={STAT_LABEL}>
                <Package size={13} className="text-ink-faint" /> Capacity
              </dt>
              <dd className={STAT_VALUE}>{vendor.capacity_units_per_month.toLocaleString("en-IN")} units/mo</dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className={STAT_LABEL}>
                <Building2 size={13} className="text-ink-faint" /> Distance
              </dt>
              <dd className={STAT_VALUE}>{vendor.distance_km !== null ? `${vendor.distance_km.toFixed(0)} km` : "—"}</dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className={STAT_LABEL}>
                <Globe2 size={13} className="text-ink-faint" /> Languages
              </dt>
              <dd className="flex flex-wrap justify-end gap-1.5">
                {vendor.languages.map((l) => (
                  <span key={l} className="rounded-full bg-surface-3 px-2 py-0.5 text-[11px] font-medium text-ink-muted">
                    {LANGUAGE_LABEL[l] ?? l}
                  </span>
                ))}
              </dd>
            </div>
          </dl>
        </div>
      </div>

      <div className="mt-4 flex items-start gap-2 rounded-lg border border-dashed border-line-strong bg-surface px-5 py-4 text-[12.5px] leading-relaxed text-ink-muted">
        <Gauge size={14} className="mt-0.5 shrink-0 text-ink-faint" />
        Sourced automatically as a candidate for compatible disruptions once verified — see the candidate rail in the
        ops console.
      </div>
    </div>
  );
}
