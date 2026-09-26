import asyncio
import logging
from dataclasses import fields
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.models import Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import utc
from app.services.current_values import Reading, upsert_current
from app.worker.grouping import read_groups
from app.worker.modbus import ModbusSource
from app.worker.scheduler import PollScheduler
from app.worker.simulator import SimulatorSource
from app.worker.sources import CommunicationError, DecodeError, PollTag, TelemetrySource, Transport

logger = logging.getLogger(__name__)


async def load_configuration(session: AsyncSession) -> list[PollTag]:
    rows = (
        await session.execute(
            select(Tag, Device, Connection)
            .join(Device, Device.id == Tag.device_id)
            .join(Connection, Connection.id == Device.connection_id)
        )
    ).all()
    return [
        PollTag(
            tag.id,
            tag.data_type,
            tag.poll_interval_ms,
            Decimal(str(tag.scale)),
            Decimal(str(tag.offset)),
            Decimal(str(tag.min_value)) if tag.min_value is not None else None,
            Decimal(str(tag.max_value)) if tag.max_value is not None else None,
            tag.enabled and device.enabled and connection.enabled,
            tag.updated_at,
            device.updated_at,
            connection.updated_at,
            tag.history_enabled,
            tag.history_mode,
            tag.history_interval_ms,
            tag.history_change_threshold,
            transport_config(connection),
            device.id,
            device.slave_id,
            tag.register_type,
            tag.address,
            tag.byte_order,
            tag.word_order,
        )
        for tag, device, connection in rows
    ]


def transport_config(connection: Connection) -> Transport:
    return Transport(
        **{
            field.name: getattr(connection, "updated_at" if field.name == "version" else field.name)
            for field in fields(Transport)
        }
    )


async def configuration_is_current(
    session: AsyncSession, tag: PollTag, enabled: bool = True
) -> bool:
    statement = (
        select(
            Tag.updated_at,
            Device.updated_at,
            Connection.updated_at,
            (Tag.enabled & Device.enabled & Connection.enabled),
        )
        .join(Device, Device.id == Tag.device_id)
        .join(Connection, Connection.id == Device.connection_id)
        .where(
            Tag.id == tag.id,
        )
        .with_for_update(read=True, of=(Tag, Device, Connection))
    )
    row = (await session.execute(statement)).first()
    return row is not None and tuple(row) == (
        tag.tag_version,
        tag.device_version,
        tag.connection_version,
        enabled,
    )


async def collect_one(
    session: AsyncSession, source: TelemetrySource, tag: PollTag,
    acquired: Reading | Exception | None = None,
) -> None:
    reading, quality, error = None, "GOOD", None
    try:
        if isinstance(acquired, Exception):
            raise acquired
        reading = acquired if acquired is not None else await source.read(tag)
        if (tag.data_type == "bool" and not isinstance(reading.value, bool)) or (
            tag.data_type != "bool" and not isinstance(reading.value, Decimal)
        ):
            raise ValueError("Source value does not match configured data type")
    except CommunicationError as exc:
        reading = None
        quality, error = "COMM_ERROR", str(exc)
        logger.debug("Tag %s acquisition failed: %s", tag.id, error)
    except DecodeError as exc:
        reading = None
        quality, error = "BAD", str(exc)
        logger.debug("Tag %s decode failure: %s", tag.id, error)
    except Exception:
        reading = None
        quality, error = "BAD", "Source could not produce a valid configured value"
        logger.exception("Tag %s source error", tag.id)
    # A short per-tag revision check avoids persisting a reading for changed/deleted configuration.
    # Full configuration is loaded only on the refresh interval.
    if await configuration_is_current(session, tag):
        previous = await session.scalar(
            select(TagCurrentValue).where(TagCurrentValue.tag_id == tag.id).with_for_update()
        )
        if (
            reading
            and previous
            and previous.source_timestamp
            and utc(previous.source_timestamp) > utc(reading.source_timestamp)
        ):
            return  # A command read-back or newer poll committed first.
        if quality != "GOOD" and (
            previous is None or previous.quality != quality or previous.error != error
        ):
            logger.warning(
                "Tag read state changed: tag_id=%s quality=%s error=%s", tag.id, quality, error
            )
        if reading and previous and previous.source and reading.source != previous.source:
            await upsert_current(
                session,
                tag.id,
                quality="BAD",
                error="Telemetry source changed",
                clear_value=True,
                history_policy=tag,
            )
        await upsert_current(
            session, tag.id, reading=reading, quality=quality, error=error, history_policy=tag
        )


async def reconcile_disabled(session: AsyncSession, tags: list[PollTag]) -> None:
    existing = dict(
        (await session.execute(select(TagCurrentValue.tag_id, TagCurrentValue.quality))).all()
    )
    for tag in tags:
        if not tag.enabled and existing.get(tag.id) != "DISABLED":
            if await configuration_is_current(session, tag, enabled=False):
                await upsert_current(
                    session, tag.id, quality="DISABLED", error=None, history_policy=tag
                )


async def poll_loop(
    database: Database, settings: Settings, stop: asyncio.Event, source: TelemetrySource | None
) -> None:
    scheduler = PollScheduler()
    loop = asyncio.get_running_loop()
    refresh_at = 0.0
    in_flight: dict[int, tuple[list[PollTag], asyncio.Task]] = {}

    async def collect(group: list[PollTag]) -> None:
        try:
            values = await source.read_many(group) if isinstance(source, ModbusSource) else {}
            for tag in group:
                try:
                    async with database.sessions() as session, session.begin():
                        await collect_one(session, source, tag, values.get(tag.id))
                except Exception:
                    logger.exception("Tag %s current-value transaction failed", tag.id)
        except Exception:
            logger.exception("Telemetry group acquisition failed")

    try:
        while not stop.is_set():
            for identifier, (group, task) in list(in_flight.items()):
                if task.done():
                    await task
                    for tag in group:
                        if scheduler.tags.get(tag.id) == tag:
                            scheduler.completed(tag, loop.time())
                    del in_flight[identifier]
            if loop.time() >= refresh_at:
                try:
                    async with database.sessions() as session, session.begin():
                        tags = await load_configuration(session)
                        await reconcile_disabled(session, tags)
                        connections = [
                            transport_config(c) for c in await session.scalars(select(Connection))
                        ]
                    new_tags = {tag.id: tag for tag in tags if tag.enabled}
                    obsolete = [
                        task for group, task in in_flight.values()
                        if any(new_tags.get(tag.id) != tag for tag in group)
                    ]
                    for task in obsolete:
                        task.cancel()
                    await asyncio.gather(*obsolete, return_exceptions=True)
                    in_flight = {
                        key: pair for key, pair in in_flight.items() if pair[1] not in obsolete
                    }
                    if isinstance(source, ModbusSource):
                        source.manager.configure(connections)
                        source.manager.probe_tags = [tag for tag in tags if tag.enabled]
                    changed = scheduler.refresh(tags if source else [], loop.time())
                    if source:
                        for identifier in changed:
                            if isinstance(source, SimulatorSource):
                                source.forget(identifier, new_tags.get(identifier))
                            else:
                                source.forget(identifier)
                    if changed:
                        logger.info(
                            "Telemetry configuration reloaded: changed_tags=%s", len(changed)
                        )
                except Exception:
                    # Do not continue collecting from a potentially invalid cached configuration.
                    scheduler.refresh([], loop.time())
                    for _, task in in_flight.values():
                        task.cancel()
                    await asyncio.gather(
                        *(task for _, task in in_flight.values()), return_exceptions=True
                    )
                    in_flight.clear()
                    logger.exception(
                        "Configuration refresh failed; polling paused until next refresh"
                    )
                refresh_at = loop.time() + settings.worker_config_refresh_seconds
            if source:
                due = scheduler.due(loop.time(), limit=max(50, len(scheduler.tags)))
                groups = read_groups(due) if isinstance(source, ModbusSource) else [[t] for t in due]
                groups.sort(key=lambda group: min(scheduler.next_due[t.id] for t in group))
                for group in groups:
                    tag = group[0]
                    if stop.is_set():
                        break
                    connection_id = tag.transport.id if tag.transport else tag.id
                    if (
                        connection_id not in in_flight
                        and len(in_flight) < settings.worker_max_parallel_connections
                    ):
                        in_flight[connection_id] = (group, asyncio.create_task(collect(group)))
            try:
                # In-flight tags remain due until completion; cap wakeups instead of busy-spinning.
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=max(0.02, min(0.1, scheduler.delay(loop.time(), refresh_at))),
                )
            except TimeoutError:
                continue
    finally:
        for _, task in in_flight.values():
            task.cancel()
        await asyncio.gather(*(task for _, task in in_flight.values()), return_exceptions=True)
