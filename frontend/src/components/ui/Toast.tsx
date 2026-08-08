"use client";

import { useEffect } from "react";
import { CheckCircle2, X } from "lucide-react";

interface ToastProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  timeout?: number;
}

export default function Toast({ title, subtitle, onClose, timeout = 6000 }: ToastProps) {
  useEffect(() => {
    const id = setTimeout(onClose, timeout);
    return () => clearTimeout(id);
  }, [onClose, timeout]);

  return (
    <div className="fixed top-20 right-6 z-[9000] max-w-md glass-panel rounded-2xl ring-1 ring-positive/30 shadow-2xl shadow-black/60 animate-fade-in border-l-4 border-l-positive">
      <div className="flex items-start gap-3 p-4">
        <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-positive" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">{title}</p>
          {subtitle && <p className="mt-1 text-xs text-ink-muted">{subtitle}</p>}
        </div>
        <button type="button" onClick={onClose} className="cursor-pointer text-ink-faint hover:text-ink">
          <X size={16} />
        </button>
      </div>
    </div>
  );
}
