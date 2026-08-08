from fastapi import APIRouter, Depends

from app.deps import require_api_key
from app.mocks.loader import store
from app.schemas.agents import AgentsStatusResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"], dependencies=[Depends(require_api_key)])


@router.get("/status", response_model=AgentsStatusResponse)
def get_agents_status() -> AgentsStatusResponse:
    return AgentsStatusResponse(agents=list(store.agents.values()))
