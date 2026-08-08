import type {
  AgentsStatusResponse,
  ApprovalDecisionRequest,
  ApprovalDecisionResponse,
  AuditTrail,
  DashboardSummary,
  Disruption,
  DisruptionList,
  DisruptionStage,
  Forecast,
  MetricsDemo,
  NegotiationOutcomeRequest,
  NegotiationOutcomeResponse,
  SettlementBatchList,
  SettlementConfirmRequest,
  SettlementConfirmResponse,
  SettlementExecuteRequest,
  SettlementExecuteResponse,
  Vendor,
  VendorContext,
  VendorDuesResponse,
  VendorList,
} from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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

function query(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) qs.set(key, String(value));
  }
  const str = qs.toString();
  return str ? `?${str}` : "";
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
};

export function wsUrl(): string {
  const base = API_BASE_URL.replace(/^http/, "ws");
  return `${base}/api/v1/live`;
}
