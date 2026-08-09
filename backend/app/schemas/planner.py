"""Remediation plan schemas — the optimized fix for a disruption."""

from pydantic import BaseModel


class PlanChange(BaseModel):
    kind: str  # PlanChangeKind: SPLIT_ORDER, SWITCH_VENDOR, PULL_FORWARD_STOCK, REDUCE_QUANTITY, EXPEDITE_FREIGHT
    vendor_id: str | None = None
    vendor_name: str | None = None
    item_sku: str
    qty: int
    unit_price_paise: int
    unit_price_display: str
    lead_time_days: int
    eta_date: str  # ISO date when the substituted order arrives
    rationale: str = ""  # LLM-generated explanation, or template fallback


class ExposureSnapshot(BaseModel):
    exposure_paise: int
    exposure_display: str


class RemediationPlan(BaseModel):
    id: str
    disruption_id: str
    created_at: str
    changes: list[PlanChange]
    before: ExposureSnapshot
    after: ExposureSnapshot
    cost_to_resolve_paise: int
    cost_to_resolve_display: str
    net_saving_paise: int
    net_saving_display: str
    requires_escalation: bool
    escalation_reason: str | None = None
    solve_ms: float
    solver: str  # "ORTOOLS_CPSAT" | "GREEDY_FALLBACK"
