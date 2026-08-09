"use client";

import { Toggle as TogglePrimitive } from "@base-ui/react/toggle";
import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group";

import { cn } from "@/lib/utils";

function ToggleGroup<Value extends string>({ className, ...props }: ToggleGroupPrimitive.Props<Value>) {
  return (
    <ToggleGroupPrimitive
      data-slot="toggle-group"
      className={cn("inline-flex items-center gap-1 rounded-md border border-line bg-surface-2 p-1", className)}
      {...props}
    />
  );
}

function ToggleGroupItem<Value extends string>({ className, ...props }: TogglePrimitive.Props<Value>) {
  return (
    <TogglePrimitive
      data-slot="toggle-group-item"
      className={cn(
        "cursor-pointer rounded-sm px-2.5 py-1 text-[12px] font-medium text-ink-muted transition-colors duration-100 hover:text-ink data-pressed:bg-accent data-pressed:text-accent-ink",
        className
      )}
      {...props}
    />
  );
}

export { ToggleGroup, ToggleGroupItem };
