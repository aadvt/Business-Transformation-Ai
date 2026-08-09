"use client";

import { Button as ButtonPrimitive } from "@base-ui/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-transparent text-[13px] font-medium whitespace-nowrap transition-colors duration-100 outline-none select-none cursor-pointer disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-ink hover:bg-accent/90",
        secondary: "border-line bg-surface-2 text-ink hover:border-line-strong hover:bg-surface-3",
        destructive: "border-critical/40 bg-transparent text-critical hover:bg-critical/10",
        outline: "border-line bg-transparent text-ink hover:bg-surface-2",
        ghost: "text-ink-muted hover:bg-surface-2 hover:text-ink",
        link: "text-accent underline-offset-4 hover:underline",
      },
      size: {
        default: "h-8 gap-1.5 px-3 py-1.5",
        sm: "h-7 gap-1.5 px-2.5 text-xs",
        lg: "h-9 gap-2 px-4",
        icon: "size-8",
        "icon-sm": "size-7",
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
