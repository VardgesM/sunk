import asyncio
import logging
from collections.abc import Awaitable, Callable

import asyncpg

from app.core.config import Settings
from app.db.session import Database
from app.schemas.telemetry import TagValueEvent
from app.services.alarms import ALARM_CHANNEL, get_event
from app.services.commands import COMMAND_CHANNEL, get_command
from app.services.current_values import CHANNEL, get_current, mark_stale

logger = logging.getLogger(__name__)
Message = dict[str, object]


class LiveHub:
    """Per-API socket fan-out only; cross-process transport is PostgreSQL NOTIFY."""

    def __init__(self, queue_size: int = 256) -> None:
        self.clients: set[asyncio.Queue[Message]] = set()
        self.queue_size = queue_size
        self.ready = False

    def subscribe(self) -> asyncio.Queue[Message]:
        queue: asyncio.Queue[Message] = asyncio.Queue(self.queue_size)
        self.clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Message]) -> None:
        self.clients.discard(queue)

    def publish(self, message: Message) -> None:
        for queue in tuple(self.clients):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"type": "resync_required"})
            else:
                queue.put_nowait(message)

    def status(self, ready: bool) -> None:
        self.ready = ready
        self.publish({"type": "stream_status", "ready": ready})
        if ready:
            self.publish({"type": "resync_required"})


async def connect_listener(settings: Settings) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        database=settings.postgres_db,
        timeout=5,
        command_timeout=5,
    )


class NotificationListener:
    def __init__(
        self, database: Database, hub: LiveHub, connect: Callable[[], Awaitable[asyncpg.Connection]]
    ) -> None:
        self.database, self.hub, self.connect = database, hub, connect
        self.pending: set[int] = set()
        self.pending_commands: set[int] = set()
        self.pending_alarms: set[int] = set()
        self.wake = asyncio.Event()
        self.overflow = False

    def notified(
        self, _connection: asyncpg.Connection, _pid: int, _channel: str, payload: str
    ) -> None:
        try:
            identifier = int(payload)
            if identifier <= 0 or identifier > 2147483647:
                raise ValueError("Invalid tag identifier")
        except ValueError:
            logger.warning("Ignored malformed telemetry notification")
            return
        pending = (
            self.pending_alarms
            if _channel == ALARM_CHANNEL
            else self.pending_commands
            if _channel == COMMAND_CHANNEL
            else self.pending
        )
        if len(pending) >= 10000:
            self.overflow = True
        else:
            pending.add(identifier)
        self.wake.set()

    async def dispatch(self) -> None:
        identifiers, self.pending = self.pending, set()
        if self.overflow:
            self.overflow = False
            self.hub.publish({"type": "resync_required"})
        commands, self.pending_commands = self.pending_commands, set()
        alarms, self.pending_alarms = self.pending_alarms, set()
        async with self.database.sessions() as session:
            for identifier in sorted(alarms):
                event = await get_event(session, identifier)
                if event:
                    self.hub.publish({"type": "alarm_event", "data": event.model_dump(mode="json")})
            for identifier in sorted(commands):
                command = await get_command(session, identifier)
                if command:
                    self.hub.publish(
                        {"type": "command_status", "data": command.model_dump(mode="json")}
                    )
            for identifier in sorted(identifiers):
                value = await get_current(session, identifier)
                self.hub.publish(
                    TagValueEvent(data=value).model_dump(mode="json")
                    if value
                    else {"type": "tag_deleted", "tag_id": identifier}
                )

    async def run(self) -> None:
        delay = 1
        while True:
            connection = None
            try:
                connection = await self.connect()
                await connection.add_listener(CHANNEL, self.notified)
                await connection.add_listener(COMMAND_CHANNEL, self.notified)
                await connection.add_listener(ALARM_CHANNEL, self.notified)
                delay = 1
                self.hub.status(True)
                while True:
                    try:
                        await asyncio.wait_for(self.wake.wait(), timeout=5)
                    except TimeoutError:
                        pass
                    self.wake.clear()
                    # Also detects half-open connections even when telemetry is idle.
                    await connection.execute("SELECT 1")
                    await self.dispatch()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PostgreSQL live listener disconnected; reconnecting")
            finally:
                self.hub.status(False)
                if connection is not None:
                    # terminate() is synchronous and bounded, including during cancellation.
                    connection.terminate()
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)


async def stale_loop(database: Database, settings: Settings) -> None:
    while True:
        try:
            async with database.sessions() as session, session.begin():
                await mark_stale(session, settings.stale_multiplier)
        except Exception:
            logger.exception("Stale-state maintenance failed; retrying")
        await asyncio.sleep(settings.stale_check_seconds)
