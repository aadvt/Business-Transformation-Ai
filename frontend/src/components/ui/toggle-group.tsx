"use client";

import { Toggle as TogglePrimitive } from "@base-ui/react/toggle";
import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group";

import { cn } from "@/lib/utils";

function ToggleGroup<Value extends string>({ className, ...props }: ToggleGroupPrimitive.Props<Value>) {
  return (
    <ToggleGroupPrimitive
      data-slot="toggle-group"
      className={cn("inline-flex items-center gap-1 rounded-full bg-surface-2 p-1", className)}
      {...props}
    />
  );
}

function ToggleGroupItem<Value extends string>({ className, ...props }: TogglePrimitive.Props<Value>) {
  return (
    <TogglePrimitive
      data-slot="toggle-group-item"
      className={cn(
        "cursor-pointer rounded-full px-3 py-1.5 text-[12px] font-medium text-ink-muted outline-none",
        "transition-[background-color,color,box-shadow] duration-200 ease-out",
        "hover:bg-surface-3 hover:text-ink",
        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
        "data-pressed:bg-accent data-pressed:text-accent-ink data-pressed:shadow-panel data-pressed:hover:bg-[color-mix(in_srgb,var(--color-accent)_88%,black)]",
        "disabled:pointer-events-none disabled:opacity-45 data-disabled:pointer-events-none data-disabled:opacity-45",
        className
      )}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
