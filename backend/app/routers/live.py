from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws_manager import live_feed

router = APIRouter(tags=["live"])


@router.websocket("/api/v1/live")
async def live_feed_ws(websocket: WebSocket) -> None:
    await live_feed.connect(websocket)
    try:
        for event in live_feed.replay_buffer():
            await websocket.send_json(event.model_dump())
        while True:
            # We don't require clients to send anything; just keep the socket open
            # and let broadcasts (including the heartbeat task) push data to it.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        live_feed.disconnect(websocket)
