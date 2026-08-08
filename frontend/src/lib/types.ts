export type PipelineStageId =
  | "sensing"
  | "diagnosis"
  | "sourcing"
  | "negotiation"
  | "governance"
  | "settlement";

export interface PipelineStageDef {
  id: PipelineStageId;
  label: string;
  description: string;
}

export const PIPELINE_STAGES: PipelineStageDef[] = [
  { id: "sensing", label: "Sensing", description: "Monitoring signals" },
  { id: "diagnosis", label: "Diagnosis", description: "Quantifying exposure" },
  { id: "sourcing", label: "Sourcing", description: "Verifying backups" },
  { id: "negotiation", label: "Negotiation", description: "Voice agent on call" },
  { id: "governance", label: "Governance", description: "Owner approval" },
  { id: "settlement", label: "Settlement", description: "Payout executed" },
];

export type DisruptionStatus =
  | "active"
  | "awaiting_approval"
  | "negotiating"
  | "settled"
  | "rejected";

export interface BackupVendor {
  id: string;
  name: string;
  verified: boolean;
  etaDays: number;
  priceDeltaPct: number;
}

export interface Disruption {
  id: string;
  vendorId: string;
  vendorName: string;
  category: string;
  issue: string;
  detectedAt: string;
  exposureINR: number;
  stageIndex: number;
  status: DisruptionStatus;
  backups: BackupVendor[];
  negotiatedTermsSummary?: string;
}

export interface Vendor {
  id: string;
  name: string;
  category: string;
  city: string;
  reliabilityPct: number;
}

export interface SettlementDue {
  id: string;
  vendorId: string;
  vendorName: string;
  amountINR: number;
  dueDate: string;
  status: "pending" | "staged" | "settled";
  sourceDisruptionId?: string;
}

export type AgentId =
  | "sentinel"
  | "diagnosis"
  | "sourcing"
  | "negotiation"
  | "governance"
  | "settlement";

export interface AgentStatus {
  id: AgentId;
  label: string;
  state: "idle" | "working" | "alert";
  detail: string;
}
