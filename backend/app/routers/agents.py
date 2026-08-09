from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.db_models import AgentRun
from app.deps import require_api_key
from app.schemas.agents import AgentState, AgentsStatusResponse
from app.schemas.enums import AgentName, AgentStatus
from app.schemas.money import utc_now_iso

router = APIRouter(prefix="/api/v1/agents", tags=["agents"], dependencies=[Depends(require_api_key)])


@router.get("/status", response_model=AgentsStatusResponse)
async def get_agents_status(db: AsyncSession = Depends(get_db)) -> AgentsStatusResponse:
    # No "current status" table exists — derived as the most recent
    # agent_runs row per agent. That table is empty until real agent
    # execution logic exists (a separate, larger task), so every agent
    # honestly reports IDLE with no current_task until then.
    rows = (await db.execute(select(AgentRun))).scalars().all()

    latest_by_agent: dict[str, AgentRun] = {}
    for run in rows:
        current = latest_by_agent.get(run.agent)
        if current is None or run.started_at > current.started_at:
            latest_by_agent[run.agent] = run

    agents = []
    for name in AgentName:
        run = latest_by_agent.get(name.value)
        if run is None:
            agents.append(
                AgentState(
                    name=name,
                    status=AgentStatus.IDLE,
                    current_task=None,
                    last_updated_at=utc_now_iso(),
                    disruption_id=None,
                )
            )
            continue
        agents.append(
            AgentState(
                name=name,
                status=AgentStatus(run.status),
                current_task=run.output_summary or run.input_summary or None,
                last_updated_at=(run.ended_at or run.started_at).isoformat(),
                disruption_id=run.disruption_id,
            )
        )
    return AgentsStatusResponse(agents=agents)
