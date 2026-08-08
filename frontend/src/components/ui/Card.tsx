import clsx from "clsx";
import type { ReactNode } from "react";

export default function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("glass-panel rounded-2xl", className)}>{children}</div>;
}
