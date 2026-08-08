from pydantic import Field

from app.schemas.common import ApiModel, Envelope
from app.schemas.enums import MemorySource


class VendorRef(ApiModel):
    """Minimal vendor reference embedded in other objects."""

    id: str
    name: str
    gstin: str


class Vendor(Envelope):
    name: str
    category: str
    gstin: str
    udyam_number: str | None = None
    phone: str
    languages: list[str] = Field(default_factory=list)
    city: str
    state: str
    reliability_score_0_100: int
    on_time_rate: float
    orders_completed: int
    disputes: int
    dues_paise: int
    dues_display: str


class VendorList(ApiModel):
    items: list[Vendor]
    total: int


class Reliability(ApiModel):
    score_0_100: int
    on_time_rate: float
    orders_completed: int
    disputes: int


class LastTerms(ApiModel):
    unit_price_paise: int
    lead_time_days: int
    payment_terms_days: int
    agreed_at: str


class Guardrails(ApiModel):
    max_unit_price_paise: int
    max_lead_time_days: int
    requires_human_above_paise: int


class VendorContextVendor(ApiModel):
    id: str
    name: str
    category: str
    gstin: str
    phone: str
    languages: list[str] = Field(default_factory=list)


class VendorContext(ApiModel):
    """Small, fast payload for the voice agent — fetched mid-phone-call."""

    vendor: VendorContextVendor
    reliability: Reliability
    last_terms: LastTerms | None
    history_summary: str = Field(max_length=400)
    briefing: str = Field(max_length=300)
    guardrails: Guardrails
    memory_source: MemorySource


class VendorDue(ApiModel):
    vendor: VendorRef
    total_due_paise: int
    total_due_display: str
    oldest_invoice_age_days: int
    invoice_count: int


class VendorDuesResponse(ApiModel):
    items: list[VendorDue]
    total_due_paise: int
    total_due_display: str
