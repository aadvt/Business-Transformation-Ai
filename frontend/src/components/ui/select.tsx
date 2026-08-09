"use client";

import { Select as SelectPrimitive } from "@base-ui/react/select";
import { ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";

function Select<Value>({ ...props }: SelectPrimitive.Root.Props<Value>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />;
}

function SelectTrigger({ className, children, ...props }: SelectPrimitive.Trigger.Props) {
  return (
    <SelectPrimitive.Trigger
      data-slot="select-trigger"
      className={cn(
        "flex h-10 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-line bg-surface-2 px-3.5 text-left text-[13px] text-ink outline-none",
        "transition-[background-color,border-color,box-shadow] duration-200 ease-out",
        "hover:border-line-strong hover:bg-surface-3",
        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
        "data-open:border-accent data-open:bg-surface",
        "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:border-line disabled:hover:bg-surface-2",
        "data-disabled:cursor-not-allowed data-disabled:opacity-45",
        className
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon>
        <ChevronsUpDown size={14} className="shrink-0 text-ink-faint" />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

function SelectValue({ ...props }: SelectPrimitive.Value.Props) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />;
}

function SelectContent({ className, children, ...props }: SelectPrimitive.Popup.Props) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Positioner sideOffset={4} className="z-50">
        <SelectPrimitive.Popup
          data-slot="select-content"
          className={cn(
            "elevated max-h-72 w-[var(--anchor-width)] overflow-y-auto rounded-md p-1.5 duration-200 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
            className
          )}
          {...props}
        >
          {children}
        </SelectPrimitive.Popup>
      </SelectPrimitive.Positioner>
    </SelectPrimitive.Portal>
  );
}

function SelectItem({ className, children, ...props }: SelectPrimitive.Item.Props) {
  return (
    <SelectPrimitive.Item
      data-slot="select-item"
      className={cn(
        "flex cursor-pointer flex-col gap-0.5 rounded-sm px-2.5 py-2 text-[13px] text-ink outline-none transition-colors duration-150",
        "hover:bg-surface-2 data-highlighted:bg-accent-dim data-highlighted:text-accent data-selected:text-accent data-selected:font-medium",
        "data-disabled:pointer-events-none data-disabled:opacity-45",
        className
      )}
      {...props}
    >
      {children}
    </SelectPrimitive.Item>
  );
}

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue };
