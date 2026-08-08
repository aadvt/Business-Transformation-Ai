"""In-memory WebSocket connection manager + ring buffer for /api/v1/live.

Kept separate from app.routers.live so other routers (approvals, settlements,
negotiations) can broadcast domain events without importing FastAPI route code.
"""

import asyncio
import uuid
from collections import deque
from typing import Any

from fastapi import WebSocket

from app.schemas.enums import WSEventType
from app.schemas.money import utc_now_iso
from app.schemas.ws import WSEvent

RING_BUFFER_SIZE = 50


class LiveFeedManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._ring_buffer: deque[WSEvent] = deque(maxlen=RING_BUFFER_SIZE)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    def replay_buffer(self) -> list[WSEvent]:
        return list(self._ring_buffer)

    async def broadcast(
        self,
        event_type: WSEventType,
        payload: dict[str, Any],
        disruption_id: str | None = None,
    ) -> WSEvent:
        event = WSEvent(
            event_id=str(uuid.uuid4()),
            type=event_type,
            at=utc_now_iso(),
            disruption_id=disruption_id,
            payload=payload,
        )
        async with self._lock:
            self._ring_buffer.append(event)
            dead: list[WebSocket] = []
            for conn in self._connections:
                try:
                    await conn.send_json(event.model_dump())
                except Exception:
                    dead.append(conn)
            for conn in dead:
                self._connections.discard(conn)
        return event


live_feed = LiveFeedManager()
