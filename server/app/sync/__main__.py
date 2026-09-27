"""Independent sync process; reconnect to PostgreSQL without restarting the native worker."""

import asyncio
import logging
import signal

from sqlalchemy import text

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.sync.client import SyncClient
from app.sync.state import initialize

logger = logging.getLogger(__name__)


async def serve(database: Database, settings: Settings, stop: asyncio.Event) -> None:
    await initialize(database, settings)
    async with database.engine.connect() as lease:
        if not await lease.scalar(text("SELECT pg_try_advisory_lock(927012)")):
            raise RuntimeError("Another sync client owns this Edge")
        try:
            client = SyncClient(database, settings)
        except Exception:
            await lease.execute(text("SELECT pg_advisory_unlock(927012)"))
            raise

        async def guard() -> None:
            while not stop.is_set():
                await lease.execute(text("SELECT 1"))
                await asyncio.sleep(1)

        tasks = [asyncio.create_task(client.run(stop)), asyncio.create_task(guard())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await lease.execute(text("SELECT pg_advisory_unlock(927012)"))
            except Exception:
                logger.warning("Sync database lease unavailable during shutdown")


async def main() -> None:
    settings = Settings()
    if settings.application_mode != "edge":
        raise RuntimeError("Sync process runs only in edge mode")
    configure_logging(settings.log_level)
    database = Database(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        while not stop.is_set():
            try:
                await serve(database, settings, stop)
            except Exception as exc:
                # Avoid exception text containing URLs, connection strings or remote data.
                logger.error("Sync lease/startup failed: %s; retrying", type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
