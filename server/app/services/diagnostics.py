"""On-demand, read-only summaries. No probes of hardware or remote services."""

import asyncio
import logging
import shutil
import socket
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic, perf_counter
from uuid import UUID

from alembic.runtime.migration import MigrationContext
from alembic.util import CommandError
from asyncpg import PostgresError
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.version import APP_VERSION
from app.models import (
    Connection,
    Device,
    EdgeInstallation,
    SyncOutbox,
    SyncState,
    Tag,
    TagCurrentValue,
)
from app.schemas.backup import BackupInfo
from app.schemas.runtime import SystemDiagnostics
from app.schemas.telemetry import utc
from app.services.current_values import is_stale
from app.services.recovery import sync_blocked

logger = logging.getLogger(__name__)
READ_ERRORS = (SQLAlchemyError, PostgresError, CommandError, OSError, TimeoutError)


def unavailable(metric: str, error: Exception) -> None:
    # Exception text may contain paths, connection parameters or malformed secret metadata.
    logger.warning("Diagnostics %s unavailable (%s)", metric, type(error).__name__)


def local_metrics(settings: Settings, result: SystemDiagnostics) -> None:
    try:
        result.hostname = socket.gethostname() or None
    except OSError as exc:
        unavailable("hostname", exc)
    directory = Path(settings.backup_directory)
    try:
        result.disk_free_bytes = shutil.disk_usage(directory).free
    except OSError as exc:
        unavailable("disk", exc)
    try:
        rows = []
        # Read existing metadata only: do not instantiate BackupStore, which creates its directory.
        try:
            paths = list(directory.iterdir())
        except FileNotFoundError:
            result.backup_status = "NONE"
            return
        for path in paths:
            if path.suffix != ".json":
                continue
            try:
                identifier = UUID(path.stem)
            except ValueError:
                continue
            if path.is_symlink() or path.stat().st_size > 256 * 1024:
                raise ValueError("Unsafe backup metadata")
            row = BackupInfo.model_validate_json(path.read_bytes())
            if row.id != identifier:
                raise ValueError("Mismatched backup metadata")
            if row.kind == "backup":
                rows.append(row)
        rows.sort(key=lambda row: utc(row.created_at), reverse=True)
        result.backup_status = "NONE"
        for index, row in enumerate(rows):
            if row.status in ("AVAILABLE", "VALIDATED", "SUCCESS"):
                artifact = directory / f"{row.id}.mmbak"
                if artifact.is_symlink() or not artifact.is_file():
                    raise ValueError("Backup artifact unavailable")
                if result.last_backup_at is None:
                    result.last_backup_at = utc(row.created_at)
                if index == 0:
                    result.backup_status = "AVAILABLE"
            elif index == 0:
                result.backup_status = "FAILED" if row.status == "FAILED" else "IN_PROGRESS"
    except (OSError, ValueError, ValidationError) as exc:
        result.backup_status, result.last_backup_at = "UNKNOWN", None
        unavailable("backup", exc)


async def revision(session: AsyncSession, settings: Settings, result: SystemDiagnostics) -> None:
    connection = await session.connection()
    result.database_revision = await connection.run_sync(
        lambda conn: MigrationContext.configure(conn).get_current_revision()
    )


async def synchronization(
    session: AsyncSession, settings: Settings, result: SystemDiagnostics
) -> None:
    if settings.application_mode == "standalone":
        result.sync_status = "DISABLED"
        return
    if await sync_blocked(session):
        result.sync_status = "PAUSED"
        return
    if settings.application_mode == "edge":
        result.pending_sync_count = await session.scalar(
            select(func.count()).select_from(SyncOutbox)
        )
        state = await session.get(SyncState, 1)
        if state is None or state.mode != "edge":
            return
        result.last_sync_at = utc(state.last_sync_at) if state.last_sync_at else None
        result.sync_status = (
            "UNAVAILABLE"
            if state.last_error
            else "CONNECTED"
            if state.last_sync_at
            and 0 <= (result.checked_at - utc(state.last_sync_at)).total_seconds() < 30
            else "DISCONNECTED"
        )
    else:
        # Cloud has heartbeats, not an acknowledged Edge sync cycle or its pending queue.
        times = list(
            await session.scalars(
                select(EdgeInstallation.last_seen_at).where(EdgeInstallation.enabled)
            )
        )
        if times:
            online = sum(
                stamp is not None and 0 <= (result.checked_at - utc(stamp)).total_seconds() < 30
                for stamp in times
            )
            result.sync_status = (
                "CONNECTED" if online == len(times) else "DEGRADED" if online else "DISCONNECTED"
            )


async def telemetry(session: AsyncSession, settings: Settings, result: SystemDiagnostics) -> None:
    statement = (
        select(
            TagCurrentValue.source_timestamp,
            TagCurrentValue.quality,
            TagCurrentValue.source,
            Tag.poll_interval_ms,
        )
        .select_from(Tag)
        .join(Device, Device.id == Tag.device_id)
        .join(Connection, Connection.id == Device.connection_id)
        .outerjoin(TagCurrentValue, TagCurrentValue.tag_id == Tag.id)
        .where(Tag.enabled, Device.enabled, Connection.enabled)
    )
    states = set()
    async for timestamp, quality, source, interval in await session.stream(statement):
        timestamp = utc(timestamp) if timestamp else None
        if timestamp and (result.last_telemetry_at is None or timestamp > result.last_telemetry_at):
            result.last_telemetry_at = timestamp
        if quality in ("BAD", "COMM_ERROR", "DISABLED"):
            states.add("UNAVAILABLE")
        elif quality == "STALE":
            states.add("STALE")
        elif timestamp is None or source is None or timestamp > result.checked_at:
            states.add("UNKNOWN")
        elif is_stale(timestamp, interval, settings.stale_multiplier, result.checked_at):
            states.add("STALE")
        else:
            states.add("FRESH" if quality == "GOOD" else "UNAVAILABLE")
    result.telemetry_status = (
        next(iter(states)) if len(states) == 1 else "DEGRADED" if states else "UNKNOWN"
    )


async def collect(
    session: AsyncSession, settings: Settings, started_monotonic: float | None
) -> SystemDiagnostics:
    result = SystemDiagnostics(
        application_version=APP_VERSION,
        application_mode=settings.application_mode,
        database_revision=None,
        checked_at=datetime.now(UTC),
        uptime_seconds=max(0, int(monotonic() - started_monotonic))
        if started_monotonic is not None
        else None,
    )
    await asyncio.to_thread(local_metrics, settings, result)
    start = perf_counter()
    try:
        async with asyncio.timeout(6):
            await session.execute(text("SELECT 1"))
        result.database_status = "OK"
        result.database_latency_ms = round((perf_counter() - start) * 1000, 2)
    except READ_ERRORS as exc:
        result.database_status = "ERROR"
        await session.rollback()
        unavailable("database", exc)
        return result
    for name, probe in (
        ("revision", revision),
        ("sync", synchronization),
        ("telemetry", telemetry),
    ):
        try:
            async with asyncio.timeout(6):
                await probe(session, settings, result)
        except READ_ERRORS as exc:
            await session.rollback()
            unavailable(name, exc)
    return result
