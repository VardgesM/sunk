import asyncio
import logging
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.services.history_retention import retention_loop
from app.worker.alarms import AlarmEngine
from app.worker.automation import AutomationEngine
from app.worker.commands import CommandProcessor
from app.worker.lease import watch_lease, worker_lease
from app.worker.modbus import ConnectionManager, ModbusSource
from app.worker.notifications import NotificationSender
from app.worker.polling import poll_loop
from app.worker.runtime import runtime_loop
from app.worker.serial_binding import SerialBinder
from app.worker.simulator import SimulatorSource

logger = logging.getLogger(__name__)


async def heartbeat(database: Database, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with asyncio.timeout(6):
                await database.ping()
            logger.info("Worker heartbeat: database reachable")
        except Exception:
            logger.exception("Worker heartbeat failed; retrying next interval")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_heartbeat_seconds)
        except TimeoutError:
            continue


async def run(settings: Settings, stop: asyncio.Event) -> None:
    if settings.application_mode == "cloud":
        raise RuntimeError("Cloud must never run the Modbus/Automation worker")
    database = Database(settings)
    if settings.application_mode == "edge":
        from app.sync.state import initialize

        await initialize(database, settings)
    manager = ConnectionManager(settings) if settings.source_mode == "modbus" else None
    source = (
        SimulatorSource(settings.simulator_failure_probability)
        if settings.source_mode == "simulator"
        else ModbusSource(manager)
        if manager
        else None
    )
    logger.info(
        "Worker running; telemetry_source=%s; physical_writes_enabled=%s",
        settings.source_mode,
        settings.modbus_writes_enabled,
    )
    tasks = [
        asyncio.create_task(heartbeat(database, settings, stop)),
        asyncio.create_task(poll_loop(database, settings, stop, source)),
        asyncio.create_task(retention_loop(database, settings, stop)),
        asyncio.create_task(runtime_loop(database, settings, stop, manager)),
        asyncio.create_task(CommandProcessor(database, settings, source).run(stop)),
        asyncio.create_task(AutomationEngine(database, settings).run(stop)),
        asyncio.create_task(AlarmEngine(database, settings).run(stop)),
        asyncio.create_task(NotificationSender(database, settings).run(stop)),
    ]
    if manager:
        tasks.append(asyncio.create_task(SerialBinder(database, settings, manager).run(stop)))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if manager:
            manager.close()
        await database.close()
        logger.info("Worker stopped")


async def main() -> None:
    settings = get_settings()
    if settings.application_mode == "cloud":
        raise RuntimeError("Cloud cannot start a transport worker")
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    # signal.signal also works on Windows, where add_signal_handler is unsupported.
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        while not stop.is_set():
            try:
                async with worker_lease(settings) as connection:
                    database_mode = await connection.fetchval(
                        "SELECT mode FROM sync_state WHERE id=1"
                    )
                    if database_mode == "cloud":
                        raise RuntimeError("Cloud database cannot run a transport worker")
                    collection = asyncio.create_task(run(settings, stop))
                    ownership = asyncio.create_task(watch_lease(connection))
                    try:
                        done, _ = await asyncio.wait(
                            [collection, ownership], return_when=asyncio.FIRST_COMPLETED
                        )
                        for task in done:
                            await task
                    finally:
                        collection.cancel()
                        ownership.cancel()
                        await asyncio.gather(collection, ownership, return_exceptions=True)
            except Exception:
                logger.exception("Worker ownership/database unavailable; transports stopped")
                if not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), 5)
                    except TimeoutError:
                        continue
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    asyncio.run(main())
