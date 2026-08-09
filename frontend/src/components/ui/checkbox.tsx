"use client";

import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox";
import { CheckIcon } from "lucide-react";

import { cn } from "@/lib/utils";

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer relative flex size-[18px] shrink-0 cursor-pointer items-center justify-center rounded-sm border border-line-strong bg-surface outline-none",
        "transition-[background-color,border-color,box-shadow] duration-200 ease-out",
        "hover:border-accent hover:bg-accent-dim",
        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
        "data-checked:border-accent data-checked:bg-accent data-checked:text-accent-ink data-checked:hover:bg-[color-mix(in_srgb,var(--color-accent)_88%,black)]",
        "data-indeterminate:border-accent data-indeterminate:bg-accent data-indeterminate:text-accent-ink",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line-strong disabled:hover:bg-surface",
        "data-disabled:cursor-not-allowed data-disabled:opacity-45",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="grid place-content-center text-current [&>svg]:size-3"
      >
        <CheckIcon strokeWidth={3} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
