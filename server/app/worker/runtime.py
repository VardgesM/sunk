"""Worker-host discovery and a bounded transport-test mailbox, never device commands."""

import asyncio
import logging
import socket
from datetime import UTC, datetime

from serial.tools.list_ports import comports
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.session import Database
from app.models import Connection, ConnectionRuntime, WorkerRuntime
from app.schemas.telemetry import utc
from app.services.runtime import upsert_runtime
from app.worker.modbus import ConnectionManager
from app.worker.sources import CommunicationError, DecodeError

logger = logging.getLogger(__name__)


def discover_ports() -> list[dict[str, str]]:
    return [{"device": port.device, "description": port.description} for port in comports()]


async def test_transport(
    database: Database,
    manager: ConnectionManager,
    identifier: int,
    token: str,
    version: datetime,
    requested: datetime,
) -> None:
    entry = manager.entries.get(identifier)
    if entry is None or utc(entry.config.version) != utc(version):
        success, message, latency = False, "Connection configuration changed; retry the test", None
    else:
        started = asyncio.get_running_loop().time()
        try:
            remaining = 30 - (datetime.now(UTC) - utc(requested)).total_seconds()
            async with asyncio.timeout(max(0.001, remaining)):
                await manager.execute(entry.config)
            success = True
            message = (
                "Serial port opened; slave communication was NOT verified"
                if entry.config.protocol == "modbus_rtu"
                else "TCP transport connected; slave/register reads were NOT verified"
            )
        except (CommunicationError, DecodeError, TimeoutError) as exc:
            success, message = False, str(exc) or "Transport test timed out"
        except Exception:
            logger.exception("Transport test failed: connection_id=%s", identifier)
            success, message = False, "Transport test failed; check worker logs and settings"
        latency = (asyncio.get_running_loop().time() - started) * 1000
    async with database.sessions() as session, session.begin():
        await session.execute(
            update(ConnectionRuntime)
            .where(
                ConnectionRuntime.connection_id == identifier,
                ConnectionRuntime.test_id == token,
            )
            .values(
                test_completed_id=token,
                test_success=success,
                test_message=message,
                test_latency_ms=latency,
            )
        )


async def runtime_loop(
    database: Database, settings: Settings, stop: asyncio.Event, manager: ConnectionManager | None
) -> None:
    discovery_at = 0.0
    ports, discovery_error = [], None
    discovered_at = None
    tasks: dict[str, asyncio.Task] = {}
    try:
        while not stop.is_set():
            try:
                now = datetime.now(UTC)
                if asyncio.get_running_loop().time() >= discovery_at:
                    try:
                        ports = await asyncio.to_thread(discover_ports)
                        discovered_at = datetime.now(UTC)
                        discovery_error = None
                    except Exception:
                        logger.exception("Serial port discovery failed")
                        ports, discovery_error = [], "Worker could not enumerate serial ports"
                    discovery_at = asyncio.get_running_loop().time() + 30
                async with database.sessions() as session, session.begin():
                    await upsert_runtime(
                        session,
                        WorkerRuntime,
                        "id",
                        dict(
                            id=1,
                            mode=settings.source_mode,
                            writes_enabled=settings.modbus_writes_enabled,
                            hostname=socket.gethostname(),
                            heartbeat_at=now,
                            serial_ports=ports,
                            discovered_at=discovered_at,
                            discovery_error=discovery_error,
                        ),
                    )
                    connections = list(
                        await session.scalars(select(Connection).with_for_update(read=True))
                    )
                    for connection in connections:
                        entry = manager.entries.get(connection.id) if manager else None
                        fields = dict(
                            connection_id=connection.id,
                            updated_at=now,
                            configuration_version=connection.updated_at,
                            state="DISCONNECTED" if connection.enabled else "DISABLED",
                        )
                        if entry and utc(entry.config.version) == utc(connection.updated_at):
                            if entry.state == "CONNECTED" and (
                                entry.client is None or not entry.client.connected
                            ):
                                entry.state = "DISCONNECTED"
                            fields.update(
                                state=entry.state,
                                last_success=entry.last_success,
                                last_error=entry.last_error,
                                last_error_at=entry.last_error_at,
                            )
                        else:
                            fields.update(last_error=None)
                        await upsert_runtime(session, ConnectionRuntime, "connection_id", fields)
                    pending = list(
                        await session.scalars(
                            select(ConnectionRuntime).where(
                                ConnectionRuntime.test_id.is_not(None),
                                (ConnectionRuntime.test_completed_id.is_(None))
                                | (
                                    ConnectionRuntime.test_id != ConnectionRuntime.test_completed_id
                                ),
                            )
                        )
                    )
                for token, task in list(tasks.items()):
                    if task.done():
                        try:
                            await task
                        except Exception:
                            logger.exception("Transport diagnostic persistence failed")
                        del tasks[token]
                for request in pending:
                    if request.test_id in tasks or manager is None or len(tasks) >= 8:
                        continue
                    tasks[request.test_id] = asyncio.create_task(
                        test_transport(
                            database,
                            manager,
                            request.connection_id,
                            request.test_id,
                            request.test_configuration_version,
                            request.test_requested_at,
                        )
                    )
            except Exception:
                logger.exception("Worker runtime status refresh failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
