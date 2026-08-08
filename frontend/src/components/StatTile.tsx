import type { ComponentType } from "react";

interface StatTileProps {
  label: string;
  value: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  tone?: "default" | "alert" | "positive";
}

export default function StatTile({ label, value, icon: Icon, tone = "default" }: StatTileProps) {
  return (
    <div className={`stat-tile stat-tile--${tone}`}>
      <div className="stat-tile__icon">
        <Icon size={20} />
      </div>
      <div>
        <p className="stat-tile__value">{value}</p>
        <p className="stat-tile__label">{label}</p>
      </div>
    </div>
  );
}
