"""A database session lock prevents two worker processes mixing sources or owning RTU buses."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from app.core.config import Settings


@asynccontextmanager
async def worker_lease(settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        database=settings.postgres_db,
        timeout=5,
        command_timeout=5,
    )
    try:
        if not await connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtext('modbus-monitor-worker'))"
        ):
            raise RuntimeError("Another telemetry worker already owns this database; stop it first")
        yield connection
    finally:
        await connection.close(timeout=2)


async def watch_lease(connection: asyncpg.Connection) -> None:
    while True:
        await asyncio.sleep(1)
        # Connection termination invalidates ownership. Fail closed: stop transport tasks.
        await connection.execute("SELECT 1")
