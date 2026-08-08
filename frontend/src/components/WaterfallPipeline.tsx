import { CheckmarkFilled, Close, RadioButton } from "@carbon/icons-react";
import { PIPELINE_STAGES } from "@/lib/types";
import type { Disruption } from "@/lib/types";
import { formatINR, formatTimeAgo } from "@/lib/format";
import StatusTag from "./StatusTag";

type NodeState = "complete" | "current" | "pending" | "invalid";

function getNodeState(disruption: Disruption, stepIndex: number): NodeState {
  if (disruption.status === "rejected") {
    if (stepIndex < disruption.stageIndex) return "complete";
    if (stepIndex === disruption.stageIndex) return "invalid";
    return "pending";
  }
  if (disruption.status === "settled") return "complete";
  if (stepIndex < disruption.stageIndex) return "complete";
  if (stepIndex === disruption.stageIndex) return "current";
  return "pending";
}

export default function WaterfallPipeline({ disruption }: { disruption: Disruption }) {
  return (
    <div className="pipeline-card">
      <div className="pipeline-card__header">
        <div>
          <span className="pipeline-card__vendor">{disruption.vendorName}</span>
          <span className="pipeline-card__issue">{disruption.issue}</span>
        </div>
        <div className="pipeline-card__header-right">
          <span className="pipeline-card__exposure">{formatINR(disruption.exposureINR)}</span>
          <StatusTag disruption={disruption} />
        </div>
      </div>

      <div className="pipeline-track">
        {PIPELINE_STAGES.map((stage, i) => {
          const state = getNodeState(disruption, i);
          return (
            <div className={`pipeline-node pipeline-node--${state}`} key={stage.id}>
              <div className="pipeline-node__dot-wrap">
                <span className="pipeline-node__dot">
                  {state === "complete" && <CheckmarkFilled size={16} />}
                  {state === "invalid" && <Close size={16} />}
                  {(state === "current" || state === "pending") && <RadioButton size={12} />}
                </span>
                {i < PIPELINE_STAGES.length - 1 && <span className="pipeline-node__connector" />}
              </div>
              <div className="pipeline-node__text">
                <span className="pipeline-node__label">{stage.label}</span>
                <span className="pipeline-node__description">{stage.description}</span>
              </div>
            </div>
          );
        })}
      </div>

      {disruption.negotiatedTermsSummary && (
        <p className="pipeline-card__summary">{disruption.negotiatedTermsSummary}</p>
      )}
      <p className="pipeline-card__timestamp">Detected {formatTimeAgo(disruption.detectedAt)}</p>
    </div>
  );
}
