"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import clsx from "clsx";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-gradient-to-br from-accent to-[#d18f2c] text-[#1a1305] shadow-lg shadow-accent/30 hover:shadow-accent/50 hover:scale-105 disabled:bg-accent/40 disabled:text-[#1a1305]/60 disabled:shadow-none disabled:scale-100",
  secondary: "glass text-ink hover:border-accent/40 disabled:opacity-40",
  danger: "bg-alert/10 text-alert border border-alert/30 hover:bg-alert/20 disabled:opacity-40",
  ghost: "bg-transparent text-ink-muted hover:bg-white/5 hover:text-ink disabled:opacity-40",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "text-xs px-3 py-1.5 gap-1.5",
  md: "text-sm px-4 py-2 gap-2",
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", icon, className, children, disabled, ...props },
  ref
) {
  return (
    <button
      ref={ref}
      disabled={disabled}
      className={clsx(
        "inline-flex items-center justify-center rounded-xl font-medium transition-all duration-200 cursor-pointer disabled:cursor-not-allowed active:scale-[0.97]",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
});

export default Button;
