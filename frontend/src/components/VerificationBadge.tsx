import { ShieldAlert, ShieldCheck } from "lucide-react";
import clsx from "clsx";

// Shared between /directory (search cards, detail hero) and the /command
// candidate rail — one visual language for "this vendor's GSTIN/Udyam
// checked out" everywhere it appears, per the D2 brief.
export default function VerificationBadge({
  verified,
  size = "md",
  className,
}: {
  verified: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const Icon = verified ? ShieldCheck : ShieldAlert;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-sm font-semibold tracking-wide uppercase",
        verified ? "bg-success/12 text-success" : "bg-neutral/12 text-neutral",
        size === "sm" ? "px-1.5 py-px text-[9px]" : "px-2 py-1 text-[11px]",
        className
      )}
    >
      <Icon size={size === "sm" ? 11 : 13} />
      {verified ? "Verified" : "Unverified"}
    </span>
  );
}
