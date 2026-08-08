import { Money, Time } from "@carbon/icons-react";
import type { Disruption } from "@/lib/types";
import { formatINR, formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

export default function DisruptionRow({ disruption }: { disruption: Disruption }) {
  return (
    <div className={`disruption-row disruption-row--${disruption.status}`}>
      <div className="disruption-row__main">
        <span className="disruption-row__vendor">{disruption.vendorName}</span>
        <span className="disruption-row__issue">{disruption.issue}</span>
      </div>
      <div className="disruption-row__side">
        <span className="disruption-row__meta">
          <Time size={14} /> {formatTimeAgo(disruption.detectedAt)}
        </span>
        <span className="disruption-row__meta">
          <Money size={14} /> {formatINR(disruption.exposureINR)}
        </span>
        <StatusTag disruption={disruption} />
      </div>
    </div>
  );
}
