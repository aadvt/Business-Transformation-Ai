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
    <div className="fixed top-20 right-6 z-[9000] max-w-md panel animate-fade-in border-l-2 border-l-success">
      <div className="flex items-start gap-3 p-3">
        <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-success" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-ink">{title}</p>
          {subtitle && <p className="mt-1 text-[12px] text-ink-muted">{subtitle}</p>}
        </div>
        <button type="button" onClick={onClose} className="cursor-pointer text-ink-faint hover:text-ink">
          <X size={16} />
        </button>
      </div>
    </div>
  );
}
