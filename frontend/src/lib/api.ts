import type {
  AgentsStatusResponse,
  AgentSheetSync,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  AuditTrail,
  DashboardSummary,
  DemoState,
  Disruption,
  DisruptionList,
  DisruptionStage,
  Forecast,
  ImpactGraph,
  MetricsDemo,
  NegotiationOutcomeRequest,
  NegotiationOutcomeResponse,
  Plan,
  PhoneMessagesResponse,
  PublicVendorDetail,
  PublicVendorList,
  PublicVendorSearchParams,
  SettlementBatchList,
  SettlementConfirmRequest,
  SettlementConfirmResponse,
  SettlementExecuteRequest,
  SettlementExecuteResponse,
  SimulateDisruptionRequest,
  SimulateDisruptionResponse,
  SimulateTarget,
  Vendor,
  VendorContext,
  VendorDuesResponse,
  VendorList,
  VendorRegistrationRequest,
  VendorRegistrationResponse,
} from "./types";
import { demoStateFixture, impactGraphFixture, planFixture, simulateTargetsFixture } from "./demoFixtures";
import { allPublicVendors, findPublicVendor, registerFixtureVendor } from "./directoryFixtures";
import { getPhoneMessagesFixture } from "./phoneFixtures";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Demo layer (D0+): serve fixtures instead of hitting the backend until its
// endpoints land. Flip to "false" (or unset) to call the real API — no other
// code change needed.
const USE_FIXTURES = process.env.NEXT_PUBLIC_USE_FIXTURES === "true";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function query(params: Record<string, string | number | boolean | string[] | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) qs.append(key, item);
    } else {
      qs.set(key, String(value));
    }
  }
  const str = qs.toString();
  return str ? `?${str}` : "";
}

function matchesPublicVendorFilters(vendor: PublicVendorDetail, params: PublicVendorSearchParams): boolean {
  if (params.category && vendor.category !== params.category) return false;
  if (params.pincode && params.radius_km !== undefined) {
    if (vendor.distance_km !== null && vendor.distance_km > params.radius_km) return false;
  }
  if (params.max_lead_time_days !== undefined && vendor.lead_time_days > params.max_lead_time_days) return false;
  if (params.min_capacity !== undefined && vendor.capacity_units_per_month < params.min_capacity) return false;
  if (params.languages && params.languages.length > 0 && !params.languages.some((l) => vendor.languages.includes(l)))
    return false;
  if (params.verified !== undefined && vendor.verified !== params.verified) return false;
  return true;
}

export const api = {
  getAgentsStatus: () => request<AgentsStatusResponse>("/api/v1/agents/status"),

  listDisruptions: (params?: { stage?: DisruptionStage; limit?: number }) =>
    request<DisruptionList>(`/api/v1/disruptions${query({ stage: params?.stage, limit: params?.limit })}`),

  getDisruption: (id: string) => request<Disruption>(`/api/v1/disruptions/${id}`),

  listVendors: (params?: { search?: string; limit?: number }) =>
    request<VendorList>(`/api/v1/vendors${query({ search: params?.search, limit: params?.limit })}`),

  getVendor: (id: string) => request<Vendor>(`/api/v1/vendors/${id}`),

  getVendorDues: () => request<VendorDuesResponse>("/api/v1/vendors/dues"),

  getVendorContext: (vendorId: string) => request<VendorContext>(`/api/v1/vendors/${vendorId}/context`),

  syncAgentSheet: (disruptionId?: string) =>
    request<AgentSheetSync>("/api/v1/agent/sync-sheet", {
      method: "POST",
      body: JSON.stringify({ disruption_id: disruptionId }),
    }),

  replayLastCall: (callId: string) =>
    request(`/api/v1/calls/${callId}/replay`, { method: "POST" }),

  getAgentSheetCsvUrl: (disruptionId?: string) =>
    `${API_BASE_URL}/api/v1/agent/vendor-sheet.csv${query({ disruption_id: disruptionId })}`,

  getDashboardSummary: () => request<DashboardSummary>("/api/v1/dashboard/summary"),

  decideApproval: (approvalId: string, body: ApprovalDecisionRequest) =>
    request<ApprovalDecisionResponse>(`/api/v1/approvals/${approvalId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  executeSettlementBatch: (batchId: string, body: SettlementExecuteRequest) =>
    request<SettlementExecuteResponse>(`/api/v1/settlements/${batchId}/execute`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listSettlementBatches: (params?: { month?: string }) =>
    request<SettlementBatchList>(`/api/v1/settlement/batch${query({ month: params?.month })}`),

  confirmSettlementBatch: (batchId: string, body: SettlementConfirmRequest) =>
    request<SettlementConfirmResponse>(`/api/v1/settlement/${batchId}/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getAuditTrail: (disruptionId: string) => request<AuditTrail>(`/api/v1/audit/${disruptionId}`),

  getMetricsDemo: () => request<MetricsDemo>("/api/v1/metrics/demo"),

  getForecast: (sku: string) => request<Forecast>(`/api/v1/forecast/${sku}`),

  postNegotiationOutcome: (negotiationId: string, body: NegotiationOutcomeRequest) =>
    request<NegotiationOutcomeResponse>(`/api/v1/negotiations/${negotiationId}/outcome`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getSimulateTargets: () =>
    USE_FIXTURES ? Promise.resolve(simulateTargetsFixture) : request<SimulateTarget[]>("/api/v1/simulate/targets"),

  simulateDisruption: (body: SimulateDisruptionRequest) =>
    USE_FIXTURES
      ? Promise.resolve<SimulateDisruptionResponse>({ disruption_id: impactGraphFixture.disruption_id, stage: "DETECTED" })
      : request<SimulateDisruptionResponse>("/api/v1/disruptions/simulate", {
          method: "POST",
          body: JSON.stringify(body),
        }),

  getImpactGraph: (disruptionId: string) =>
    USE_FIXTURES
      ? Promise.resolve(impactGraphFixture)
      : request<ImpactGraph>(`/api/v1/disruptions/${disruptionId}/impact`),

  getPlan: (disruptionId: string) =>
    USE_FIXTURES ? Promise.resolve(planFixture) : request<Plan>(`/api/v1/disruptions/${disruptionId}/plan`),

  getPhoneMessages: () =>
    USE_FIXTURES
      ? Promise.resolve<PhoneMessagesResponse>({ items: getPhoneMessagesFixture() })
      : request<PhoneMessagesResponse>("/api/v1/phone/messages"),

  resetDemo: () =>
    USE_FIXTURES ? Promise.resolve(demoStateFixture) : request<DemoState>("/api/v1/demo/reset", { method: "POST" }),

  getDemoState: () => (USE_FIXTURES ? Promise.resolve(demoStateFixture) : request<DemoState>("/api/v1/demo/state")),

  // Public vendor directory (D2) — unauthenticated, separate from the ops
  // dashboard's /vendors. See directoryFixtures.ts for the fixture-mode
  // implementation (including live, session-scoped registration).
  listPublicVendors: (params: PublicVendorSearchParams = {}) =>
    USE_FIXTURES
      ? Promise.resolve<PublicVendorList>({
          items: allPublicVendors().filter((v) => matchesPublicVendorFilters(v, params)),
          total: allPublicVendors().filter((v) => matchesPublicVendorFilters(v, params)).length,
        })
      : request<PublicVendorList>(
          `/api/v1/public/vendors${query({
            category: params.category,
            pincode: params.pincode,
            radius_km: params.radius_km,
            max_lead_time_days: params.max_lead_time_days,
            min_capacity: params.min_capacity,
            languages: params.languages,
            verified: params.verified,
          })}`
        ),

  getPublicVendor: (id: string) =>
    USE_FIXTURES
      ? (() => {
          const vendor = findPublicVendor(id);
          return vendor ? Promise.resolve(vendor) : Promise.reject(new ApiError(404, "Vendor not found."));
        })()
      : request<PublicVendorDetail>(`/api/v1/public/vendors/${id}`),

  registerVendor: (body: VendorRegistrationRequest) =>
    USE_FIXTURES
      ? (() => {
          const result = registerFixtureVendor(body);
          if (!result.ok) return Promise.reject(new ApiError(422, result.reason));
          return Promise.resolve<VendorRegistrationResponse>({ vendor: result.vendor });
        })()
      : request<VendorRegistrationResponse>("/api/v1/public/vendors/register", {
          method: "POST",
          body: JSON.stringify(body),
        }),
};

export function wsUrl(): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}/api/v1/live`;
}
