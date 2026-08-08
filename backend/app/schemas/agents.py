from app.schemas.common import ApiModel
from app.schemas.enums import AgentName, AgentStatus


class AgentState(ApiModel):
    name: AgentName
    status: AgentStatus
    current_task: str | None = None
    last_updated_at: str
    disruption_id: str | None = None


class AgentsStatusResponse(ApiModel):
    agents: list[AgentState]
