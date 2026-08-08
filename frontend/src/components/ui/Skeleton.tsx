import clsx from "clsx";

export default function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("shimmer bg-white/5 rounded-xl", className)} />;
}
