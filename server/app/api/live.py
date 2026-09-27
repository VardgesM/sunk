import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.schemas.telemetry import utc
from app.services.auth import COOKIE, authenticated
from app.services.live import LiveHub

router = APIRouter()


@router.websocket("/api/ws/live")
async def live(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    settings = websocket.app.state.settings
    if origin and origin not in settings.cors_origins:
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    async def identity():
        async with websocket.app.state.database.sessions() as session:
            return await authenticated(session, websocket.cookies.get(COOKIE))

    initial = await identity()
    if not initial:
        await websocket.close(code=4401, reason="Authentication required")
        return
    expires_at = utc(initial[1].expires_at)
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
            if datetime.now(UTC) >= expires_at:
                await websocket.close(code=4401, reason="Session expired")
                return
            async with asyncio.timeout(10):
                await websocket.send_json(message)

    async def receive() -> None:
        # No subscriptions/commands accepted in v1. Reading detects disconnects promptly.
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return

    async def guard() -> None:
        while True:
            await asyncio.sleep(1)
            if not await identity():
                await websocket.close(code=4401, reason="Session expired or revoked")
                return

    tasks = [
        asyncio.create_task(send()),
        asyncio.create_task(receive()),
        asyncio.create_task(guard()),
    ]
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
