"use client";

import { useEffect, useRef } from "react";
import clsx from "clsx";

interface CheckboxProps {
  checked: boolean;
  indeterminate?: boolean;
  onChange: () => void;
  disabled?: boolean;
  "aria-label"?: string;
  className?: string;
}

export default function Checkbox({ checked, indeterminate, onChange, disabled, className, ...props }: CheckboxProps) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = Boolean(indeterminate);
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      className={clsx(
        "h-4 w-4 rounded-sm border border-line-strong bg-surface-2 accent-accent cursor-pointer disabled:cursor-not-allowed disabled:opacity-40",
        className
      )}
      {...props}
    />
  );
}
