from pydantic import Field
from app.schemas.common import ApiModel

class CallStartRequest(ApiModel):
    disruption_id: str
    vendor_id: str
    mode: str = Field(default="LIVE", pattern="^(LIVE|REPLAY)$")

class CallSessionResponse(ApiModel):
    id: str
    disruption_id: str | None
    vendor_id: str | None
    status: str
    source: str
    started_at: str
    ended_at: str | None = None
    language: str | None = None
    phone: str | None = None
    briefing_snapshot: dict
    guardrails: dict
    transcript: list
    extracted: dict
    validation: dict
    correlation_method: str | None = None
    outcome_status: str | None = None
