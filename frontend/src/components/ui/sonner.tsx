"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon } from "lucide-react";

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
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
          "--normal-bg": "var(--color-surface-2)",
          "--normal-text": "var(--color-ink)",
          "--normal-border": "var(--color-line-strong)",
          "--border-radius": "var(--radius-md)",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "!shadow-[0_12px_32px_-8px_rgba(0,0,0,0.7)] !text-[13px]",
          title: "!text-ink !font-medium",
          description: "!text-ink-muted",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
