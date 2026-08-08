"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { ApprovalDecision, Channel, DisruptionStage } from "./types";

// Demo-mode actor identities — there's no auth/session system in the
// contract-and-mocks phase, so these match the example values used
// throughout backend/CONTRACT.md's fixtures.
const WEB_APPROVER = "priya.sharma@mahe-industries.in";
const FINANCE_OPS = "finance.ops@mahe-industries.in";

export const queryKeys = {
  agentsStatus: ["agentsStatus"] as const,
  disruptions: (stage?: DisruptionStage) => ["disruptions", stage ?? "all"] as const,
  disruption: (id: string) => ["disruption", id] as const,
  vendors: (search?: string) => ["vendors", search ?? ""] as const,
  vendorDues: ["vendorDues"] as const,
  dashboardSummary: ["dashboardSummary"] as const,
  settlementBatches: (month?: string) => ["settlementBatches", month ?? "all"] as const,
};

export function useAgentsStatus() {
  return useQuery({
    queryKey: queryKeys.agentsStatus,
    queryFn: api.getAgentsStatus,
    refetchInterval: 20000,
  });
}

export function useDisruptions(stage?: DisruptionStage) {
  return useQuery({
    queryKey: queryKeys.disruptions(stage),
    queryFn: () => api.listDisruptions({ stage }),
  });
}

export function useDisruption(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.disruption(id ?? ""),
    queryFn: () => api.getDisruption(id as string),
    enabled: Boolean(id),
  });
}

export function useVendors(search?: string) {
  return useQuery({
    queryKey: queryKeys.vendors(search),
    queryFn: () => api.listVendors({ search }),
  });
}

export function useVendorDues() {
  return useQuery({
    queryKey: queryKeys.vendorDues,
    queryFn: api.getVendorDues,
  });
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: queryKeys.dashboardSummary,
    queryFn: api.getDashboardSummary,
    refetchInterval: 30000,
  });
}

export function useSettlementBatches(month?: string) {
  return useQuery({
    queryKey: queryKeys.settlementBatches(month),
    queryFn: () => api.listSettlementBatches({ month }),
  });
}

export function useDecideApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ approvalId, decision, channel = "WEB" }: { approvalId: string; decision: ApprovalDecision; channel?: Channel }) =>
      api.decideApproval(approvalId, {
        decision,
        channel,
        decided_by: WEB_APPROVER,
        idempotency_key: crypto.randomUUID(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["disruptions"] });
      queryClient.invalidateQueries({ queryKey: ["disruption"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useExecuteSettlementBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId }: { batchId: string }) =>
      api.executeSettlementBatch(batchId, { executed_by: FINANCE_OPS, idempotency_key: crypto.randomUUID() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settlementBatches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}

export function useConfirmSettlementBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ batchId }: { batchId: string }) =>
      api.confirmSettlementBatch(batchId, { confirmed_by: FINANCE_OPS, idempotency_key: crypto.randomUUID() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settlementBatches"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.dashboardSummary });
    },
  });
}
