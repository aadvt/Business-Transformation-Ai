from typing import Any

from app.schemas.common import ApiModel
from app.schemas.enums import AgentName


class AuditEntry(ApiModel):
    id: str
    at: str
    # Real audit_log entries cover human actions too (actor_type=HUMAN), not
    # just agents — agent is populated only when actor_type == "AGENT" so
    # existing readers of .agent degrade gracefully instead of breaking.
    actor_type: str | None = None
    actor: str | None = None
    agent: AgentName | None = None
    action: str
    detail: dict[str, Any] = {}
    input_summary: str | None = None
    output_summary: str | None = None
    # Tamper-evident hash chain — real column on audit_log, not present on
    # agent_runs-sourced entries.
    prev_hash: str | None = None
    hash: str | None = None


class AuditTrail(ApiModel):
    disruption_id: str
    entries: list[AuditEntry]
