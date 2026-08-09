from app.schemas.common import ApiModel
from app.schemas.enums import AgentName


class AuditEntry(ApiModel):
    id: str
    at: str
    agent: AgentName
    action: str
    detail: str
    input_summary: str | None = None
    output_summary: str | None = None


class AuditTrail(ApiModel):
    disruption_id: str
    entries: list[AuditEntry]
