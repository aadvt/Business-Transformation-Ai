"use client";

import { useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { ChevronDown, Clock, MapPin, Star } from "lucide-react";
import clsx from "clsx";
import VerificationBadge from "@/components/VerificationBadge";
import type { CandidateScoreComponents, SourcingCandidate } from "@/lib/types";
import { api } from "@/lib/api";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { CANDIDATE_STAGGER_MS } from "./graphVisuals";

const SCORE_LABEL: Record<keyof CandidateScoreComponents, string> = {
  reliability: "Reliability",
  lead_time: "Lead time",
  price: "Price",
  geography: "Geography",
  relationship: "Relationship",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-0.5 flex items-center justify-between text-[10.5px] text-ink-muted">
        <span>{label}</span>
        <span className="numeric">{Math.round(value * 100)}</span>
      </div>
      <div className="h-1 overflow-hidden rounded-sm bg-surface-3">
        <div className="h-full rounded-sm bg-accent" style={{ width: `${Math.round(value * 100)}%` }} />
      </div>
    </div>
  );
}

function CandidateCard({ candidate }: { candidate: SourcingCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const verified = candidate.verification.status === "VERIFIED";
  const gstinVerified = candidate.verification.gstin_status === "VERIFIED";
  const priceDelta = candidate.price_delta_pct ?? 0;
  const [briefingOpen, setBriefingOpen] = useState(false);
  const [context, setContext] = useState<Awaited<ReturnType<typeof api.getVendorContext>> | null>(null);

  function openBriefing() {
    setBriefingOpen(true);
    if (!context) api.getVendorContext(candidate.vendor_id).then(setContext).catch(() => undefined);
  }

  return (
    <motion.div
      id={`candidate-card-${candidate.vendor_id}`}
      variants={{ hidden: { opacity: 0, x: 28 }, show: { opacity: 1, x: 0 } }}
      className="rounded-lg border border-line bg-surface p-3"
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <p className="text-[13px] font-medium text-ink">{candidate.name}</p>
        <VerificationBadge verified={verified} gstinVerified={gstinVerified} size="sm" />
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-muted">
        {candidate.distance_km !== undefined && (
          <span className="inline-flex items-center gap-1">
            <MapPin size={11} /> {candidate.distance_km.toFixed(0)} km
          </span>
        )}
        <span className="inline-flex items-center gap-1">
          <Clock size={11} /> {candidate.quoted_lead_time_days}d lead
        </span>
        {candidate.reliability_score_0_100 !== undefined && (
          <span className="inline-flex items-center gap-1">
            <Star size={11} /> {candidate.reliability_score_0_100}/100
          </span>
        )}
      </div>

      <div className="mb-2 flex items-center justify-between">
        <span className="numeric text-[12px] font-medium text-ink">
          {priceDelta === 0 ? "Same price" : (
            <span className={priceDelta < 0 ? "text-success" : "text-critical"}>
              {priceDelta > 0 ? "+" : ""}
              {priceDelta.toFixed(1)}% vs incumbent
            </span>
          )}
        </span>
        {candidate.languages && candidate.languages.length > 0 && (
          <div className="flex gap-1">
            {candidate.languages.map((l) => (
              <span key={l} className="rounded-sm bg-surface-2 px-1 py-px text-[9px] font-medium text-ink-muted uppercase">
                {l}
              </span>
            ))}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between gap-2 rounded-md bg-surface-2 px-2 py-1.5 text-left transition-colors hover:bg-surface-3"
      >
        <div className="flex-1">
          <div className="mb-0.5 flex items-center justify-between text-[10px] text-ink-faint">
            <span>Composite score</span>
            <span className="numeric">{Math.round(candidate.match_score * 100)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-sm bg-surface-3">
            <div className="h-full rounded-sm bg-accent" style={{ width: `${Math.round(candidate.match_score * 100)}%` }} />
          </div>
        </div>
        <ChevronDown size={13} className={clsx("shrink-0 text-ink-faint transition-transform", expanded && "rotate-180")} />
      </button>

      {expanded && candidate.score_components && (
        <div className="mt-2 space-y-1.5 border-t border-line pt-2">
          {(Object.keys(SCORE_LABEL) as (keyof CandidateScoreComponents)[]).map((key) => (
            <ScoreBar key={key} label={SCORE_LABEL[key]} value={candidate.score_components![key]} />
          ))}
        </div>
      )}
      <button type="button" onClick={openBriefing} className="mt-2 text-[11px] font-medium text-accent underline decoration-dotted underline-offset-2">
        View briefing
      </button>
      <Dialog open={briefingOpen} onOpenChange={setBriefingOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Briefing for {candidate.name}</DialogTitle>
            <DialogDescription>Exactly what the voice agent was given.</DialogDescription>
          </DialogHeader>
          {context ? (
            <div className="space-y-4">
              <p className="text-lg leading-relaxed text-ink">“{context.briefing}”</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md bg-surface-2 p-3"><p className="eyebrow">Target price</p><p className="numeric text-lg">₹{(context.last_terms?.unit_price_paise ?? candidate.quoted_unit_price_paise) / 100}</p></div>
                <div className="rounded-md bg-surface-2 p-3"><p className="eyebrow">Max price</p><p className="numeric text-lg">₹{context.guardrails.max_unit_price_paise / 100}</p></div>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px] text-ink-muted">
                <span>Language: {context.vendor.languages.join(", ")}</span><span>Max lead time: {context.guardrails.max_lead_time_days}d</span>
                <span>Last agreed terms: {context.last_terms ? `₹${context.last_terms.unit_price_paise / 100} · ${context.last_terms.lead_time_days}d` : "None"}</span><span>Reliability: {context.reliability.score_0_100}/100</span>
              </div>
            </div>
          ) : <p className="text-sm text-ink-muted">Loading briefing…</p>}
        </DialogContent>
      </Dialog>
    </motion.div>
  );
}

export default function CandidateRail({
  candidates,
  onHoverCandidate,
  syncStatus,
  onSync,
  csvUrl,
}: {
  candidates: SourcingCandidate[];
  onHoverCandidate: (vendorId: string | null) => void;
  syncStatus?: "SYNCED" | "UNAVAILABLE" | "PENDING";
  onSync?: () => void;
  csvUrl?: string;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-3 py-2.5">
        <p className="eyebrow">Sourcing candidates</p>
        <p className="mt-0.5 text-[11px] text-ink-muted">Hover a card to see which node it patches.</p>
      </div>

      <motion.div
        initial="hidden"
        animate="show"
        variants={{ show: { transition: { staggerChildren: CANDIDATE_STAGGER_MS / 1000 } } }}
        className="flex-1 space-y-2 overflow-y-auto p-3"
      >
        {candidates.map((c) => (
          <div key={c.vendor_id} onMouseEnter={() => onHoverCandidate(c.vendor_id)} onMouseLeave={() => onHoverCandidate(null)}>
            <CandidateCard candidate={c} />
          </div>
        ))}
      </motion.div>

      <div className="border-t border-line px-3 py-2.5">
        {syncStatus === "PENDING" && <p className="mb-2 text-[11px] text-ink-muted"><span className="mr-1 inline-block animate-spin">◌</span>Briefing the voice agent…</p>}
        {syncStatus === "SYNCED" && <p className="mb-2 text-[11px] text-success">✓ {candidates.length} vendors briefed to the calling agent</p>}
        {syncStatus === "UNAVAILABLE" && <p className="mb-2 text-[11px] text-amber-600">Sheet sync unavailable — <a className="underline" href={csvUrl}>download CSV</a></p>}
        <Link href="/directory" target="_blank" className="text-[11px] text-ink-muted underline decoration-dotted underline-offset-2 hover:text-ink">
          All candidates come from the public directory →
        </Link>
      </div>
    </div>
  );
}
