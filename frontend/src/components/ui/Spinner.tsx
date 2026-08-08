import clsx from "clsx";
import { Loader2 } from "lucide-react";

export default function Spinner({ size = 16, className, label }: { size?: number; className?: string; label?: string }) {
  return (
    <span className={clsx("inline-flex items-center gap-1.5 text-ink-muted", className)}>
      <Loader2 size={size} className="animate-spin" />
      {label && <span className="text-xs">{label}</span>}
    </span>
  );
}
