// Mirrors backend/app/schemas/*.py and backend/app/schemas/enums.py exactly.
// See backend/CONTRACT.md for the full annotated contract.

// ---- Enums (backend/app/schemas/enums.py) ----

export type DisruptionStage =
  | "DETECTED"
  | "DIAGNOSED"
  | "SOURCING"
  | "AWAITING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "NEGOTIATING"
  | "NEGOTIATED"
  | "SETTLEMENT_PENDING"
  | "SETTLED"
  | "CLOSED"
  | "FAILED";

export type AgentName = "SENTINEL" | "DIAGNOSIS" | "SOURCING" | "NEGOTIATION" | "SETTLEMENT" | "GOVERNANCE";

export type AgentStatusValue = "IDLE" | "RUNNING" | "DONE" | "BLOCKED" | "ERROR";

export type DisruptionType =
  | "DELIVERY_DELAY"
  | "VENDOR_UNRESPONSIVE"
  | "QUALITY_REJECTION"
  | "STOCKOUT_RISK"
  | "PRICE_SHOCK"
  | "LOGISTICS_HOLD";

export type RootCause =
  | "CUSTOMS_HOLD"
  | "TRANSPORT_BREAKDOWN"
  | "VENDOR_CAPACITY"
  | "RAW_MATERIAL_SHORTAGE"
  | "QUALITY_FAILURE"
  | "FINANCIAL_DISTRESS"
  | "UNKNOWN";

export type VerificationStatus = "VERIFIED" | "UNVERIFIED" | "FAILED" | "UNAVAILABLE";

export type ApprovalDecision = "APPROVE" | "REJECT" | "REQUEST_OPTIONS";

export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "OPTIONS_REQUESTED";

export type Channel = "WEB" | "WHATSAPP" | "VOICE" | "SYSTEM";

export type DetectorSource = "RULE_BASED" | "TTM_FORECAST";

export type IntegrationStatus = "LIVE" | "STUB" | "UNAVAILABLE" | "NOT_CONFIGURED";

export type MemorySource = "SUPERMEMORY" | "DB_ONLY" | "UNAVAILABLE";

export type ForecastModel = "granite-timeseries-ttm-r2" | "RULE_BASED";

export type WSEventType =
  | "AGENT_STATUS_CHANGED"
  | "DISRUPTION_CREATED"
  | "STAGE_CHANGED"
  | "EXPOSURE_COMPUTED"
  | "CANDIDATES_FOUND"
  | "APPROVAL_REQUESTED"
  | "APPROVAL_DECIDED"
  | "NEGOTIATION_UPDATE"
  | "SETTLEMENT_STAGED"
  | "FORECAST_ALERT"
  | "HEARTBEAT"
  | "IMPACT_COMPUTED"
  | "PLAN_PROPOSED"
  | "CALL_STARTED"
  | "CALL_TRANSCRIPT"
  | "CALL_FIELD_EXTRACTED"
  | "CALL_ENDED"
  | "INGEST_PROGRESS"
  | "BRIEFING_READY"
  | "AGENT_SHEET_SYNCED";

// ---- Common (backend/app/schemas/common.py) ----

export interface Envelope {
  id: string;
  created_at: string;
  updated_at: string;
}

// ---- Agents (backend/app/schemas/agents.py) ----

export interface AgentState {
  name: AgentName;
  status: AgentStatusValue;
  current_task: string | null;
  last_updated_at: string;
  disruption_id: string | null;
}

export interface AgentsStatusResponse {
  agents: AgentState[];
}

// ---- Vendors (backend/app/schemas/vendors.py) ----

export interface VendorRef {
  id: string;
  name: string;
  gstin: string;
}

export interface Vendor extends Envelope {
  name: string;
  category: string;
  gstin: string;
  udyam_number: string | null;
  phone: string;
  languages: string[];
  city: string;
  state: string;
  lat: number;
  lng: number;
  reliability_score_0_100: number;
  on_time_rate: number;
  orders_completed: number;
  disputes: number;
  dues_paise: number;
  dues_display: string;
}

export interface VendorList {
  items: Vendor[];
  total: number;
}

export interface Reliability {
  score_0_100: number;
  on_time_rate: number;
  orders_completed: number;
  disputes: number;
}

export interface LastTerms {
  unit_price_paise: number;
  lead_time_days: number;
  payment_terms_days: number;
  agreed_at: string;
}

export interface Guardrails {
  max_unit_price_paise: number;
  max_lead_time_days: number;
  requires_human_above_paise: number;
}

export interface VendorContextVendor {
  id: string;
  name: string;
  category: string;
  gstin: string;
  phone: string;
  languages: string[];
}

export interface VendorContext {
  vendor: VendorContextVendor;
  reliability: Reliability;
  last_terms: LastTerms | null;
  history_summary: string;
  briefing: string;
  guardrails: Guardrails;
  memory_source: MemorySource;
}

export interface AgentSheetSync {
  status: "SYNCED" | "UNAVAILABLE" | "PENDING";
  rows_written: number;
  worksheet: string;
  synced_at: string;
  reason?: string;
  csv_fallback_url?: string;
}

export interface VendorDue {
  vendor: VendorRef;
  total_due_paise: number;
  total_due_display: string;
  oldest_invoice_age_days: number;
  invoice_count: number;
}

export interface VendorDuesResponse {
  items: VendorDue[];
  total_due_paise: number;
  total_due_display: string;
}

// ---- Disruptions (backend/app/schemas/disruptions.py) ----

export interface ExposureBreakdownItem {
  label: string;
  amount_paise: number;
  amount_display: string;
  basis: string;
}

export interface Exposure {
  total_paise: number;
  total_display: string;
  confidence: number;
  breakdown: ExposureBreakdownItem[];
}

export interface GuardianCheck {
  status: string;
  passed: boolean;
}

export interface Diagnosis {
  root_cause: RootCause;
  narrative: string;
  evidence: string[];
  guardian: GuardianCheck;
}

export interface CandidateVerification {
  status: VerificationStatus;
  gstin_status: VerificationStatus;
  udyam_status: VerificationStatus;
  checked_at: string;
  source: string;
}

export interface CandidateScoreComponents {
  reliability: number;
  lead_time: number;
  price: number;
  geography: number;
  relationship: number;
}

export interface SourcingCandidate {
  vendor_id: string;
  name: string;
  match_score: number;
  verification: CandidateVerification;
  quoted_lead_time_days: number;
  quoted_unit_price_paise: number;
  // D2 additions for the /command candidate rail — optional so existing
  // consumers of Disruption.candidates (pre-D2) are unaffected. Provisional
  // until a real CONTRACT.md documents them (see chat history: no backend
  // commit for D2 exists yet).
  distance_km?: number;
  reliability_score_0_100?: number;
  languages?: string[];
  price_delta_pct?: number;
  score_components?: CandidateScoreComponents;
}

export interface Approval {
  id: string;
  status: ApprovalStatus;
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
  channel: Channel | null;
}

export interface NegotiationTerm {
  unit_price_paise: number;
  lead_time_days: number;
  payment_terms_days: number;
}

export interface Negotiation {
  id: string;
  vendor_id: string;
  status: string;
  opening_terms: NegotiationTerm | null;
  final_terms: NegotiationTerm | null;
  rounds: number;
  transcript_summary: string;
  guardian: GuardianCheck;
}

export interface TimelineEvent {
  stage: DisruptionStage;
  at: string;
  agent: AgentName;
  note: string;
}

export interface Disruption {
  id: string;
  type: DisruptionType;
  stage: DisruptionStage;
  detected_at: string;
  vendor: VendorRef;
  affected_po_ids: string[];
  headline: string;
  exposure: Exposure;
  diagnosis: Diagnosis;
  candidates: SourcingCandidate[];
  approval: Approval | null;
  negotiation: Negotiation | null;
  timeline: TimelineEvent[];
  detector_source: DetectorSource;
}

export interface DisruptionSummary {
  id: string;
  type: DisruptionType;
  stage: DisruptionStage;
  detected_at: string;
  vendor: VendorRef;
  headline: string;
  exposure_total_paise: number;
  exposure_total_display: string;
  detector_source: DetectorSource;
}

export interface DisruptionList {
  items: DisruptionSummary[];
  total: number;
}

export interface ApprovalDecisionRequest {
  decision: ApprovalDecision;
  channel: Channel;
  decided_by: string;
  note?: string;
  idempotency_key: string;
}

export interface ApprovalDecisionResponse {
  approval: Approval;
  disruption_id: string;
  new_stage: DisruptionStage;
}

// ---- Settlement (backend/app/schemas/settlement.py) ----

export interface SettlementLine {
  vendor: VendorRef;
  invoice_id: string;
  amount_paise: number;
  amount_display: string;
  due_date: string;
}

export interface SettlementBatch extends Envelope {
  month: string;
  status: string;
  total_paise: number;
  total_display: string;
  lines: SettlementLine[];
  confirmed_at: string | null;
  confirmed_by: string | null;
}

export interface SettlementBatchList {
  items: SettlementBatch[];
  total: number;
}

export interface SettlementExecuteRequest {
  idempotency_key: string;
  executed_by: string;
}

export interface TransactionAgentHandoff {
  thread_id: string;
  status: string;
  review_text: string | null;
}

export interface SettlementExecuteResponse {
  batch: SettlementBatch;
  transaction_agent: TransactionAgentHandoff | null;
}

export interface SettlementConfirmRequest {
  idempotency_key: string;
  confirmed_by: string;
}

export interface SettlementConfirmResponse {
  batch: SettlementBatch;
}

export interface NegotiationOutcomeRequest {
  outcome: string;
  final_unit_price_paise?: number;
  final_lead_time_days?: number;
  final_payment_terms_days?: number;
  transcript_summary: string;
  idempotency_key: string;
}

export interface NegotiationOutcomeResponse {
  negotiation_id: string;
  status: string;
  disruption_id: string;
  new_stage: string;
}

// ---- Dashboard (backend/app/schemas/dashboard.py) ----

export interface StageCount {
  stage: DisruptionStage;
  count: number;
}

export interface DashboardSummary {
  active_disruptions: number;
  exposure_at_risk_paise: number;
  exposure_at_risk_display: string;
  exposure_mitigated_paise: number;
  exposure_mitigated_display: string;
  disruptions_closed_today: number;
  stage_counts: StageCount[];
  vendors_dues_total_paise: number;
  vendors_dues_total_display: string;
  updated_at: string;
}

// ---- Audit (backend/app/schemas/audit.py) ----

export interface AuditEntry {
  id: string;
  at: string;
  agent: AgentName;
  action: string;
  detail: string;
  input_summary: string | null;
  output_summary: string | null;
}

export interface AuditTrail {
  disruption_id: string;
  entries: AuditEntry[];
}

// ---- Metrics (backend/app/schemas/metrics.py) ----

export interface LatencyStat {
  p50: number;
  p95: number;
  last: number;
}

export interface Latency {
  detection_to_alert_seconds: LatencyStat;
  alert_to_decision_seconds: LatencyStat;
  decision_to_negotiated_seconds: LatencyStat;
  end_to_end_seconds: LatencyStat;
}

export interface Totals {
  exposure_identified_paise: number;
  exposure_identified_display: string;
  exposure_mitigated_paise: number;
  exposure_mitigated_display: string;
  disruptions_closed: number;
}

export interface Integrations {
  watsonx: IntegrationStatus;
  guardian: IntegrationStatus;
  supermemory: IntegrationStatus;
  verification: IntegrationStatus;
  ttm: IntegrationStatus;
  orchestrate: IntegrationStatus;
  neon: IntegrationStatus;
}

export interface MetricsDemo {
  latency: Latency;
  totals: Totals;
  integrations: Integrations;
}

// ---- Forecast (backend/app/schemas/forecast.py) ----

export interface ForecastPoint {
  at: string;
  value: number;
}

export interface Forecast {
  sku: string;
  history: ForecastPoint[];
  forecast: ForecastPoint[];
  reorder_point: number;
  projected_breach_at: string | null;
  model: ForecastModel;
}

// ---- WebSocket live feed (backend/app/schemas/ws.py + CONTRACT.md catalogue) ----

export interface WSEventPayloads {
  AGENT_STATUS_CHANGED: { agent: AgentName; status: AgentStatusValue };
  DISRUPTION_CREATED: { headline: string };
  STAGE_CHANGED: { stage: DisruptionStage };
  EXPOSURE_COMPUTED: { total_paise: number; total_display: string };
  CANDIDATES_FOUND: { count: number };
  APPROVAL_REQUESTED: { channel: Channel };
  APPROVAL_DECIDED: { approval_id: string; decision: ApprovalDecision; new_stage: DisruptionStage };
  NEGOTIATION_UPDATE: { negotiation_id: string; status: string };
  SETTLEMENT_STAGED: { batch_id: string; status: string };
  FORECAST_ALERT: { sku: string; projected_breach_at: string | null };
  HEARTBEAT: Record<string, never>;
  // Demo-layer (D0+) event payloads. Backend's D0 handoff documented these
  // shapes (see chat history — CONTRACT.md/openapi.json were reported
  // updated but as of D1 the repo shows no such commit, no `demo` router,
  // and `simulate.py` unchanged from Phase 4b). Kept in sync with the
  // reported shapes anyway since they're more specific than a guess; verify
  // against a real CONTRACT.md the moment one actually exists.
  IMPACT_COMPUTED: { node_count: number; impacted_node_ids: string[]; max_severity_state: GraphNodeState };
  PLAN_PROPOSED: { plan_id: string; changes: { kind: PlanChangeKind; description: string }[] };
  CALL_STARTED: { call_id: string; vendor_id: string; status: CallStatus };
  CALL_TRANSCRIPT: { call_id: string; speaker: string; text: string };
  CALL_FIELD_EXTRACTED: { call_id: string; field: string; value: string | number };
  CALL_ENDED: { call_id: string; status: CallStatus; duration_seconds: number };
  INGEST_PROGRESS: { ingest_id: string; status: IngestStatus; progress_pct: number };
  BRIEFING_READY: { vendor_id: string; briefing: string };
  AGENT_SHEET_SYNCED: AgentSheetSync;
}

export interface WSEvent<T extends WSEventType = WSEventType> {
  event_id: string;
  type: T;
  at: string;
  disruption_id: string | null;
  payload: WSEventPayloads[T];
}

// ---- UI-only pipeline phase grouping (not a backend concept) ----
// Groups the 11-value DisruptionStage enum into the 6 conceptual phases the
// product story is told in: Sensing, Diagnosis, Sourcing, Negotiation,
// Governance, Settlement.

export type PipelinePhaseId = "sensing" | "diagnosis" | "sourcing" | "negotiation" | "governance" | "settlement";

export interface PipelinePhaseDef {
  id: PipelinePhaseId;
  label: string;
  description: string;
  stages: DisruptionStage[];
}

export const PIPELINE_PHASES: PipelinePhaseDef[] = [
  { id: "sensing", label: "Sensing", description: "Monitoring signals", stages: ["DETECTED"] },
  { id: "diagnosis", label: "Diagnosis", description: "Quantifying exposure", stages: ["DIAGNOSED"] },
  { id: "sourcing", label: "Sourcing", description: "Verifying backups", stages: ["SOURCING"] },
  { id: "negotiation", label: "Negotiation", description: "Voice agent on call", stages: ["NEGOTIATING", "NEGOTIATED"] },
  { id: "governance", label: "Governance", description: "Owner approval", stages: ["AWAITING_APPROVAL", "APPROVED", "REJECTED"] },
  {
    id: "settlement",
    label: "Settlement",
    description: "Payout executed",
    stages: ["SETTLEMENT_PENDING", "SETTLED", "CLOSED", "FAILED"],
  },
];

export function phaseIndexForStage(stage: DisruptionStage): number {
  const idx = PIPELINE_PHASES.findIndex((p) => p.stages.includes(stage));
  return idx === -1 ? 0 : idx;
}

export function isTerminalStage(stage: DisruptionStage): boolean {
  return stage === "SETTLED" || stage === "CLOSED";
}

export function isFailedStage(stage: DisruptionStage): boolean {
  return stage === "REJECTED" || stage === "FAILED";
}

// ---- Demo layer (D0-D7) — UI-only additions ahead of the backend, which is
// building to these shapes in parallel. Provisional until backend's
// CONTRACT.md update lands; treat field names as likely-stable, not final. ----

export type GraphNodeKind = "VENDOR" | "ITEM" | "LINE" | "ORDER" | "PLANT";

export type GraphNodeState = "HEALTHY" | "AT_RISK" | "IMPACTED" | "SUBSTITUTED";

export type ScenarioKind = "BACKED_OUT" | "PRICE_HIKE" | "DELAYED" | "SHUT_DOWN";

export type CallStatus = "DIALING" | "CONNECTED" | "NEGOTIATING" | "CONFIRMED" | "FAILED" | "ENDED";

export type PlanChangeKind = "SPLIT_ORDER" | "SWITCH_VENDOR" | "PULL_FORWARD_STOCK" | "REDUCE_QUANTITY" | "EXPEDITE_FREIGHT";

export type IngestStatus = "QUEUED" | "PARSING" | "RESOLVED" | "FAILED";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  state: GraphNodeState;
  layer: number;
  badges: string[];
  detail?: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  state: GraphNodeState;
  weight?: number;
}

export interface ImpactGraph {
  disruption_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  summary: {
    impacted_node_count: number;
    at_risk_order_count: number;
    exposure_paise: number;
    exposure_display: string;
    tier: string;
  };
}

export interface SimulateTarget {
  vendor_id: string;
  name: string;
  category: string;
  open_po_count: number;
  downstream_line_count: number;
  est_exposure_paise: number;
  recommended_kinds: ScenarioKind[];
}

export interface DemoState {
  stage_counts: Record<string, number>;
  integrations: Record<string, string>;
  ttm_loaded: boolean;
  ws_clients: number;
  db_roundtrip_ms: number;
}

// Request/response pair for the new vendor+kind simulate flow — not given
// literally in the D0 brief, but api.ts's `simulateDisruption(body)` needs a
// typed body/response, and this is the shape implied by `SimulateTarget` +
// `ScenarioKind`. Confirm against backend's CONTRACT.md once it lands.
export interface SimulateDisruptionRequest {
  vendor_id: string;
  kind: ScenarioKind;
  effective_date: string;
}

export interface SimulateDisruptionResponse {
  disruption_id: string;
  stage: DisruptionStage;
}

// ---- Public vendor directory (D2) — unauthenticated endpoints, separate
// from the ops dashboard's /vendors. Provisional pending a real CONTRACT.md
// for these; no backend commit for D2 exists yet (see chat history). ----

export interface VerificationEvidence {
  gstin_structure_valid: boolean;
  gstin_checksum_valid: boolean;
  state_code: string | null;
  state_code_resolved: boolean;
  udyam_format_valid: boolean;
  source: string;
  checked_at: string;
}

export interface PublicVendor {
  id: string;
  name: string;
  category: string;
  city: string;
  state: string;
  pincode: string;
  distance_km: number | null;
  lead_time_days: number;
  capacity_units_per_month: number;
  reliability_score_0_100: number;
  languages: string[];
  verified: boolean;
  gstin_masked: string;
}

export interface PublicVendorList {
  items: PublicVendor[];
  total: number;
}

export interface PublicVendorDetail extends PublicVendor {
  verification: VerificationEvidence;
  reliability: Reliability;
  orders_completed: number;
}

export interface PublicVendorSearchParams {
  category?: string;
  pincode?: string;
  radius_km?: number;
  max_lead_time_days?: number;
  min_capacity?: number;
  languages?: string[];
  verified?: boolean;
}

export interface VendorRegistrationRequest {
  name: string;
  category: string;
  gstin: string;
  udyam_number?: string;
  phone: string;
  languages: string[];
  city: string;
  state: string;
  pincode: string;
  capacity_units_per_month: number;
  lead_time_days: number;
}

export interface VendorRegistrationResponse {
  vendor: PublicVendorDetail;
}

// ---- Plan diff (D3) — the CP-SAT (or greedy-fallback) sourcing plan shown
// on /command after PLAN_PROPOSED. Provisional pending a real CONTRACT.md;
// PLAN_PROPOSED's WS payload (see WSEventPayloads above) only carries a
// plan_id + a summary of changes, so the full Plan is fetched separately,
// same pattern as ImpactGraph after IMPACT_COMPUTED. ----

export interface PlanRowItem {
  vendor_id: string;
  vendor_name: string;
  item: string;
  qty: number;
  unit_price_paise: number;
  unit_price_display: string;
  lead_time_days: number;
  eta: string;
}

export interface PlanChangeDetail {
  id: string;
  kind: PlanChangeKind;
  description: string;
  rationale: string;
  // Both sides of the diff for this change. SPLIT_ORDER: 1 current -> 2
  // proposed. SWITCH_VENDOR/REDUCE_QUANTITY/EXPEDITE_FREIGHT: 1 -> 1.
  // PULL_FORWARD_STOCK: 0 current -> 1 proposed (an internal action, not a
  // purchase — no left-hand counterpart by design).
  current: PlanRowItem[];
  proposed: PlanRowItem[];
}

export type SolverName = "OR_TOOLS_CP_SAT" | "GREEDY_FALLBACK";

export interface Plan {
  id: string;
  disruption_id: string;
  changes: PlanChangeDetail[];
  exposure_before_paise: number;
  exposure_before_display: string;
  exposure_after_paise: number;
  exposure_after_display: string;
  cost_to_resolve_paise: number;
  cost_to_resolve_display: string;
  net_saving_paise: number;
  net_saving_display: string;
  requires_escalation: boolean;
  escalation_reason: string | null;
  solver: SolverName;
  solve_ms: number;
}

// ---- Phone mock (D4) — GET /api/v1/phone/messages backing the WhatsApp Web
// mock at /phone. Provisional pending a real CONTRACT.md. ----

export type PhoneMessageKind = "TEXT" | "APPROVAL_CARD" | "SYSTEM";

export interface PhoneMessage {
  id: string;
  kind: PhoneMessageKind;
  from: "AGENT" | "OWNER";
  text: string | null;
  at: string;
  // Present when kind === "APPROVAL_CARD".
  approval_id?: string;
  disruption_id?: string;
  headline?: string;
  exposure_display?: string;
  plan_summary?: string[];
  status?: ApprovalStatus;
}

export interface PhoneMessagesResponse {
  items: PhoneMessage[];
}
