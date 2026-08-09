"use client";

import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/* Soft Logic buttons: rounded 12px controls that carry weight through fill and
   a soft ambient shadow rather than an outline. The focus ring is always the
   accent, offset against the page field so it survives on any surface. */
const buttonVariants = cva(
  [
    "inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-transparent",
    "font-medium whitespace-nowrap select-none cursor-pointer outline-none",
    "transition-[background-color,border-color,color,box-shadow] duration-200 ease-out",
    "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
    "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none",
    "data-disabled:pointer-events-none data-disabled:cursor-not-allowed data-disabled:opacity-45",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ],
  {
    variants: {
      variant: {
        default:
          "bg-accent text-accent-ink shadow-panel hover:bg-[color-mix(in_srgb,var(--color-accent)_88%,black)] hover:shadow-panel-hover active:bg-[color-mix(in_srgb,var(--color-accent)_78%,black)] active:shadow-panel",
        secondary:
          "border-line bg-surface-2 text-ink hover:border-line-strong hover:bg-surface-3 active:bg-surface-4",
        destructive:
          "bg-critical text-white shadow-panel hover:bg-[color-mix(in_srgb,var(--color-critical)_88%,black)] hover:shadow-panel-hover active:bg-[color-mix(in_srgb,var(--color-critical)_78%,black)] active:shadow-panel focus-visible:ring-critical",
        outline:
          "border-line-strong bg-transparent text-ink hover:border-line-strong hover:bg-surface-2 active:bg-surface-3",
        ghost: "text-ink-muted hover:bg-surface-2 hover:text-ink active:bg-surface-3",
        link: "text-accent underline-offset-4 hover:text-accent-bright hover:underline",
      },
      size: {
        default: "h-10 px-6 py-3 text-sm",
        sm: "h-8 gap-1.5 px-3.5 text-[13px]",
        lg: "h-12 gap-2.5 px-8 text-[15px]",
        icon: "size-10",
        "icon-sm": "size-8 [&_svg:not([class*='size-'])]:size-3.5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

interface ButtonProps
  extends Omit<ButtonPrimitive.Props, "className">,
    VariantProps<typeof buttonVariants> {
  className?: string;
  icon?: ReactNode;
}

function Button({ className, variant, size, icon, children, ...props }: ButtonProps) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    >
      {icon}
      {children}
    </ButtonPrimitive>
  );
}

export { Button, buttonVariants };
