from app.schemas.common import ApiModel, Envelope
from app.schemas.vendors import VendorRef


class SettlementLine(ApiModel):
    vendor: VendorRef
    invoice_id: str
    amount_paise: int
    amount_display: str
    due_date: str


class SettlementBatch(Envelope):
    month: str
    status: str
    total_paise: int
    total_display: str
    lines: list[SettlementLine]
    confirmed_at: str | None = None
    confirmed_by: str | None = None


class SettlementBatchList(ApiModel):
    items: list[SettlementBatch]
    total: int


class SettlementExecuteRequest(ApiModel):
    idempotency_key: str
    executed_by: str


class SettlementExecuteResponse(ApiModel):
    batch: SettlementBatch


class SettlementConfirmRequest(ApiModel):
    idempotency_key: str
    confirmed_by: str


class SettlementConfirmResponse(ApiModel):
    batch: SettlementBatch


class NegotiationOutcomeRequest(ApiModel):
    outcome: str
    final_unit_price_paise: int | None = None
    final_lead_time_days: int | None = None
    final_payment_terms_days: int | None = None
    transcript_summary: str
    idempotency_key: str


class NegotiationOutcomeResponse(ApiModel):
    negotiation_id: str
    status: str
    disruption_id: str
    new_stage: str
