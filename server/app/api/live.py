import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.live import LiveHub

router = APIRouter()


@router.websocket("/api/ws/live")
async def live(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    settings = websocket.app.state.settings
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=1008, reason="Origin not allowed")
        return
    await websocket.accept()
    hub: LiveHub = websocket.app.state.live_hub
    queue = hub.subscribe()

    async def send() -> None:
        await websocket.send_json({"type": "ready", "version": 1, "listener_ready": hub.ready})
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                message = {
                    "type": "heartbeat",
                    "listener_ready": hub.ready,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            async with asyncio.timeout(10):
                await websocket.send_json(message)

    async def receive() -> None:
        # No subscriptions/commands accepted in v1. Reading detects disconnects promptly.
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, TimeoutError, OSError):
        pass  # Per-client disconnection; other clients continue independently.
    finally:
        hub.unsubscribe(queue)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass  # A peer may already have closed the socket.
