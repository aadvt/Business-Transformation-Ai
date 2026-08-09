"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react";

/* Toasts are just another floating layer, so they borrow the same white
   surface, hairline and ambient float shadow as menus and dialogs. */
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4 text-success" />,
        info: <InfoIcon className="size-4 text-info" />,
        warning: <TriangleAlertIcon className="size-4 text-warning" />,
        error: <OctagonXIcon className="size-4 text-critical" />,
        loading: <Loader2Icon className="size-4 animate-spin text-ink-muted" />,
      }}
      style={
        {
          "--normal-bg": "var(--color-surface)",
          "--normal-text": "var(--color-ink)",
          "--normal-border": "var(--color-line)",
          "--border-radius": "var(--radius-md)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "elevated !text-[13px]",
          title: "!text-ink !font-medium",
          description: "!text-ink-muted",
          actionButton: "!bg-accent !text-accent-ink !rounded-sm",
          cancelButton: "!bg-surface-2 !text-ink-muted !rounded-sm",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
