from pydantic import Field

from app.schemas.common import ApiModel, Envelope
from app.schemas.enums import (
    AgentName,
    ApprovalDecision,
    ApprovalStatus,
    Channel,
    DetectorSource,
    DisruptionStage,
    DisruptionType,
    RootCause,
    VerificationStatus,
)
from app.schemas.vendors import VendorRef


class ExposureBreakdownItem(ApiModel):
    label: str
    amount_paise: int
    amount_display: str
    basis: str


class Exposure(ApiModel):
    total_paise: int
    total_display: str
    confidence: float
    breakdown: list[ExposureBreakdownItem]


class GuardianCheck(ApiModel):
    status: str
    passed: bool


class Diagnosis(ApiModel):
    root_cause: RootCause
    narrative: str
    evidence: list[str]
    guardian: GuardianCheck


class CandidateVerification(ApiModel):
    status: VerificationStatus
    gstin_status: VerificationStatus
    udyam_status: VerificationStatus
    checked_at: str
    source: str


class SourcingCandidate(ApiModel):
    vendor_id: str
    name: str
    match_score: float
    verification: CandidateVerification
    quoted_lead_time_days: int
    quoted_unit_price_paise: int
    score_components: dict | None = None  # {reliability, lead_time, price, geography, relationship}


class Approval(ApiModel):
    id: str
    status: ApprovalStatus
    requested_at: str
    decided_at: str | None
    decided_by: str | None
    channel: Channel | None


class NegotiationTerm(ApiModel):
    unit_price_paise: int
    lead_time_days: int
    payment_terms_days: int


class Negotiation(ApiModel):
    id: str
    vendor_id: str
    status: str
    opening_terms: NegotiationTerm | None = None
    final_terms: NegotiationTerm | None = None
    rounds: int
    transcript_summary: str
    guardian: GuardianCheck


class TimelineEvent(ApiModel):
    stage: DisruptionStage
    at: str
    agent: AgentName
    note: str


class Disruption(ApiModel):
    id: str
    type: DisruptionType
    stage: DisruptionStage
    detected_at: str
    vendor: VendorRef
    affected_po_ids: list[str]
    headline: str
    exposure: Exposure
    diagnosis: Diagnosis
    candidates: list[SourcingCandidate]
    approval: Approval | None
    negotiation: Negotiation | None
    timeline: list[TimelineEvent]
    detector_source: DetectorSource


class DisruptionSummary(ApiModel):
    """Lighter shape used in list views."""

    id: str
    type: DisruptionType
    stage: DisruptionStage
    detected_at: str
    vendor: VendorRef
    headline: str
    exposure_total_paise: int
    exposure_total_display: str
    detector_source: DetectorSource


class DisruptionList(ApiModel):
    items: list[DisruptionSummary]
    total: int


class ApprovalDecisionRequest(ApiModel):
    decision: ApprovalDecision
    channel: Channel
    decided_by: str
    note: str | None = None
    idempotency_key: str


class ApprovalDecisionResponse(ApiModel):
    approval: Approval
    disruption_id: str
    new_stage: DisruptionStage
