import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agents.detectors import ttm_forecast  # importing this registers TTM into Sentinel.DETECTORS
from app.agents.sentinel import run_sentinel_loop
from app.config import settings
from app.constants import DEFAULT_ORG_ID
from app.db import keepalive
from app.db.session import check_connectivity
from app.mocks.scripted_replay import run_heartbeat, run_scripted_replay
from app.observability import configure_logging, set_correlation_id
from app.routers import (
    agents,
    approvals,
    agent,
    webhooks,
    audit,
    dashboard,
    demo,
    disruptions,
    forecast,
    live,
    metrics,
    negotiations,
    phone,
    public,
    settlements,
    simulate,
    vendors,
)

configure_logging(logging.INFO)
logger = logging.getLogger("sanjeevani")

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.use_mocks:
        try:
            rtt_ms = check_connectivity()
            logger.info(f"Database connectivity OK — SELECT 1 round-trip {rtt_ms:.0f}ms (cold Neon compute shows up here)")
        except Exception:
            logger.exception("Database connectivity check FAILED at startup — is DATABASE_URL reachable?")
        keepalive.start()
        await ttm_forecast.start_background_load()  # schedules on a worker thread, returns immediately
        _background_tasks.append(asyncio.create_task(run_sentinel_loop(DEFAULT_ORG_ID)))

    _background_tasks.append(asyncio.create_task(run_heartbeat()))
    if settings.mock_live_replay:
        _background_tasks.append(asyncio.create_task(run_scripted_replay()))

    yield

    for task in _background_tasks:
        task.cancel()
    if not settings.use_mocks:
        keepalive.stop()


app = FastAPI(
    title="Sanjeevani Backend",
    description="Sanjeevani supply-chain disruption system backend.",
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


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Every log line emitted while handling this request — including from the
    LLM and Guardian layers — carries this id. Honours an inbound
    X-Correlation-ID so a trace can span the frontend and the voice agent too."""
    cid = set_correlation_id(request.headers.get("X-Correlation-ID"))
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = cid
    return response

app.include_router(agents.router)
app.include_router(disruptions.router)
app.include_router(vendors.router)
app.include_router(public.router)  # D2: public vendor directory, no API key required
app.include_router(dashboard.router)
app.include_router(approvals.router)
app.include_router(agent.router)
app.include_router(webhooks.router)
app.include_router(settlements.router)
app.include_router(audit.router)
app.include_router(metrics.router)
app.include_router(forecast.router)
app.include_router(negotiations.router)
app.include_router(phone.router)  # D4: WhatsApp mock message thread
app.include_router(simulate.router)
app.include_router(demo.router)
app.include_router(live.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
