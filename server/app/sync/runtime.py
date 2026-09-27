from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.models import EdgeInstallation, SyncMapping, WorkerRuntime
from app.schemas.telemetry import utc


async def effective_worker(session, settings, entity=None, identifier=None):
    if settings.application_mode != "cloud":
        return await session.get(WorkerRuntime, 1)
    if entity is None:
        return None
    mapping = await session.scalar(
        select(SyncMapping).where(
            SyncMapping.entity == entity, SyncMapping.cloud_id == identifier, ~SyncMapping.deleted
        )
    )
    edge = await session.get(EdgeInstallation, mapping.edge_id) if mapping else None
    if not edge or not edge.enabled or not edge.last_seen_at or not edge.runtime:
        return None
    heartbeat = datetime.fromisoformat(edge.runtime["heartbeat_at"])
    return SimpleNamespace(
        mode=edge.runtime["mode"],
        writes_enabled=edge.runtime["writes_enabled"]
        and (edge.runtime["mode"] != "modbus" or settings.modbus_writes_enabled),
        hostname=edge.name,
        heartbeat_at=min(utc(heartbeat), utc(edge.last_seen_at)),
    )


async def maintenance(database, settings):
    import asyncio
    import logging

    from app.sync.remote import expire_remote

    while True:
        try:
            async with database.sessions() as session, session.begin():
                await expire_remote(session)
        except Exception:
            logging.getLogger(__name__).error("Cloud request expiry maintenance failed")
        await asyncio.sleep(1)
