import clsx from "clsx";
import type { ReactNode } from "react";

export default function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("panel", className)}>{children}</div>;
}
