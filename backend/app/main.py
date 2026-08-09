import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.mocks.scripted_replay import run_heartbeat, run_scripted_replay
from app.routers import (
    agents,
    approvals,
    audit,
    dashboard,
    disruptions,
    forecast,
    live,
    metrics,
    negotiations,
    settlements,
    vendors,
)

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    _background_tasks.append(asyncio.create_task(run_heartbeat()))
    if settings.mock_live_replay:
        _background_tasks.append(asyncio.create_task(run_scripted_replay()))
    yield
    for task in _background_tasks:
        task.cancel()


app = FastAPI(
    title="Sanjeevani Backend",
    description="Postgres-backed backend for the Sanjeevani supply-chain disruption system.",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "dev" else settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(disruptions.router)
app.include_router(vendors.router)
app.include_router(dashboard.router)
app.include_router(approvals.router)
app.include_router(settlements.router)
app.include_router(audit.router)
app.include_router(metrics.router)
app.include_router(forecast.router)
app.include_router(negotiations.router)
app.include_router(live.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
