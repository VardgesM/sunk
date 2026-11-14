"""Deletion excludes concurrent config changes and physical command execution.

Acquire before configuration/command row locks; shared holders may run independently.
This is a database transaction lock, never a second Modbus transport lock.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_configuration_lifecycle(session: AsyncSession, *, exclusive: bool = False) -> None:
    if session.get_bind().dialect.name == "postgresql":
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        await session.execute(text(f"SELECT {function}(927013)"))
