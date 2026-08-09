"""Background tasks that keep the WS /api/v1/live feed moving in mock mode.

Two independent loops: a 20s heartbeat, and a 45s scripted disruption replay that
cycles through a small story so the frontend has live data to build against
without needing a real detection pipeline running.
"""

import asyncio

from app.mocks.loader import store
from app.schemas.enums import AgentName, AgentStatus, DisruptionStage, WSEventType
from app.ws_manager import live_feed

HEARTBEAT_INTERVAL_SECONDS = 20
SCRIPT_INTERVAL_SECONDS = 45

_SCRIPT_DISRUPTION_ID = "228bdcbe-3b9e-42a4-a84f-2f42c48ec664"

_SCRIPT_STEPS: list[tuple[WSEventType, dict, bool]] = [
    (WSEventType.AGENT_STATUS_CHANGED, {"agent": AgentName.DIAGNOSIS, "status": AgentStatus.RUNNING}, False),
    (WSEventType.STAGE_CHANGED, {"stage": DisruptionStage.DIAGNOSED}, True),
    (WSEventType.EXPOSURE_COMPUTED, {"total_paise": 260000000, "total_display": "₹26,00,000"}, True),
    (WSEventType.AGENT_STATUS_CHANGED, {"agent": AgentName.SOURCING, "status": AgentStatus.RUNNING}, False),
    (WSEventType.STAGE_CHANGED, {"stage": DisruptionStage.SOURCING}, True),
    (WSEventType.CANDIDATES_FOUND, {"count": 2}, True),
    (WSEventType.STAGE_CHANGED, {"stage": DisruptionStage.AWAITING_APPROVAL}, True),
    (WSEventType.APPROVAL_REQUESTED, {"channel": "WEB"}, True),
]


async def run_heartbeat() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        await live_feed.broadcast(WSEventType.HEARTBEAT, payload={})


async def run_scripted_replay() -> None:
    while True:
        await asyncio.sleep(SCRIPT_INTERVAL_SECONDS)
        await live_feed.broadcast(
            WSEventType.DISRUPTION_CREATED,
            payload={"headline": store.disruptions[_SCRIPT_DISRUPTION_ID].headline},
            disruption_id=_SCRIPT_DISRUPTION_ID,
        )
        for event_type, payload, tagged in _SCRIPT_STEPS:
            await asyncio.sleep(2)
            await live_feed.broadcast(
                event_type,
                payload=payload,
                disruption_id=_SCRIPT_DISRUPTION_ID if tagged else None,
            )
