import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import clsx from "clsx";

// Shared between /directory (search cards, detail hero) and the /command
// candidate rail — one visual language for "this vendor's GSTIN/Udyam
// checked out" everywhere it appears, per the D2 brief.
//
// Three states, not two, because the two checks can disagree and usually do:
// GSTIN is an offline checksum we can always settle, while Udyam needs a live
// provider that isn't configured in this deployment. Collapsing that into a
// bare "Unverified" would deny a check that genuinely passed, so a
// GSTIN-verified vendor says exactly that and no more. `verified` still means
// both checks passed.
export default function VerificationBadge({
  verified,
  gstinVerified = false,
  size = "md",
  className,
}: {
  verified: boolean;
  gstinVerified?: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const state = verified ? "full" : gstinVerified ? "partial" : "none";
  const { Icon, label, tone } = {
    full: { Icon: ShieldCheck, label: "Verified", tone: "bg-success-dim text-success" },
    partial: { Icon: ShieldQuestion, label: "GSTIN verified", tone: "bg-info-dim text-info" },
    none: { Icon: ShieldAlert, label: "Unverified", tone: "bg-neutral-dim text-neutral" },
  }[state];

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-full font-semibold tracking-wide uppercase",
        tone,
        size === "sm" ? "px-2 py-0.5 text-[9px]" : "px-2.5 py-1 text-[11px]",
        className
      )}
    >
      <Icon size={size === "sm" ? 11 : 13} />
      {label}
    </span>
  );
}
