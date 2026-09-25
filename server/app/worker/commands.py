"""Only this processor may issue physical Modbus writes. Never replay ambiguous writes."""

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text, update

from app.core.config import Settings
from app.db.session import Database
from app.models import Command, Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import utc
from app.services.commands import TERMINAL, command_value, notify_command, validate_write
from app.services.current_values import Reading, upsert_current
from app.services.encoding import encode_registers, verification_matches
from app.worker.decoder import decode_registers, register_count
from app.worker.modbus import READ_METHODS, ModbusSource
from app.worker.polling import transport_config
from app.worker.simulator import SimulatorSource
from app.worker.sources import CommunicationError, DecodeError, PollTag

logger = logging.getLogger(__name__)


class CommandExpired(ValueError):
    pass


def poll_tag(tag: Tag, device: Device, connection: Connection) -> PollTag:
    return PollTag(
        id=tag.id,
        data_type=tag.data_type,
        poll_interval_ms=tag.poll_interval_ms,
        scale=Decimal(str(tag.scale)),
        offset=Decimal(str(tag.offset)),
        min_value=Decimal(str(tag.min_value)) if tag.min_value is not None else None,
        max_value=Decimal(str(tag.max_value)) if tag.max_value is not None else None,
        enabled=tag.enabled and device.enabled and connection.enabled,
        tag_version=tag.updated_at,
        device_version=device.updated_at,
        connection_version=connection.updated_at,
        history_enabled=tag.history_enabled,
        history_mode=tag.history_mode,
        history_interval_ms=tag.history_interval_ms,
        history_change_threshold=tag.history_change_threshold,
        transport=transport_config(connection),
        device_id=device.id,
        slave_id=device.slave_id,
        register_type=tag.register_type,
        address=tag.address,
        byte_order=tag.byte_order,
        word_order=tag.word_order,
    )


class CommandProcessor:
    def __init__(
        self, database: Database, settings: Settings, source: ModbusSource | SimulatorSource | None
    ) -> None:
        self.database, self.settings, self.source = database, settings, source

    async def transition(
        self, identifier: int, status: str, error: str | None = None, attempt: int | None = None
    ) -> None:
        async with self.database.sessions() as session, session.begin():
            fields = dict(status=status, error_message=error, revision=Command.revision + 1)
            if status in TERMINAL:
                fields["completed_at"] = datetime.now(UTC)
            if attempt is not None:
                fields["attempt_count"] = attempt
            await session.execute(
                update(Command)
                .where(Command.id == identifier, Command.status.not_in(TERMINAL))
                .values(**fields)
            )
            await notify_command(session, identifier)
        logger.info(
            "Command state: command_id=%s status=%s attempt=%s error=%s",
            identifier,
            status,
            attempt,
            error,
        )

    async def recover(self) -> None:
        # Called once after acquiring exclusive worker ownership. A crashed action may have happened.
        async with self.database.sessions() as session, session.begin():
            ids = list(
                await session.scalars(
                    select(Command.id).where(Command.status.in_(("EXECUTING", "VERIFYING")))
                )
            )
            for identifier in ids:
                await session.execute(
                    update(Command)
                    .where(Command.id == identifier)
                    .values(
                        status="FAILED",
                        completed_at=datetime.now(UTC),
                        revision=Command.revision + 1,
                        error_message="Worker interrupted; physical outcome may be unknown. Not replayed; inspect actual value before a new command.",
                    )
                )
                await notify_command(session, identifier)

    async def claim(self) -> int | None:
        async with self.database.sessions() as session, session.begin():
            command = await session.scalar(
                select(Command)
                .where(Command.status == "QUEUED")
                .order_by(Command.created_at, Command.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if command is None:
                return None
            now = datetime.now(UTC)
            expired = (
                now >= utc(command.expires_at)
                or (now - utc(command.created_at)).total_seconds()
                >= self.settings.command_max_age_seconds
            )
            command.status = "EXPIRED" if expired else "EXECUTING"
            command.revision += 1
            if expired:
                command.completed_at, command.error_message = (
                    now,
                    "Queued command exceeded its maximum age",
                )
            else:
                command.started_at = now
            await notify_command(session, command.id)
            return None if expired else command.id

    async def process(self, identifier: int) -> None:
        sent = False
        for attempt in range(1, self.settings.command_max_attempts + 1):
            try:
                await self.transition(
                    identifier, "VERIFYING" if sent else "EXECUTING", attempt=attempt
                )
                async with self.database.sessions() as session, session.begin():
                    if session.get_bind().dialect.name == "postgresql":
                        await session.execute(text("SET LOCAL lock_timeout = '2000ms'"))
                    command = await session.get(Command, identifier)
                    if command.status in TERMINAL:
                        return
                    row = (
                        await session.execute(
                            select(Tag, Device, Connection)
                            .join(Device, Device.id == Tag.device_id)
                            .join(Connection, Connection.id == Device.connection_id)
                            .where(Tag.id == command.tag_id)
                            .with_for_update(read=True, of=(Tag, Device, Connection))
                        )
                    ).one()
                    tag, device, connection = row
                    value = command_value(command, "requested")
                    validate_write(tag, device, connection, value)
                    if any(
                        utc(getattr(command, name + "_version")) != utc(entity.updated_at)
                        for name, entity in (
                            ("tag", tag),
                            ("device", device),
                            ("connection", connection),
                        )
                    ):
                        raise ValueError(
                            "Target configuration changed after enqueue; create a new command"
                        )
                    if (
                        command.source != "manual"
                        or command.telemetry_mode != self.settings.source_mode
                    ):
                        raise ValueError("Command source/mode does not match this worker")
                    if isinstance(self.source, ModbusSource) and (
                        not self.settings.modbus_writes_enabled or not command.physical_confirmed
                    ):
                        raise ValueError("Physical writes are disabled or not confirmed")
                    if self.source is None:
                        raise ValueError("Telemetry source is disabled")
                    config = poll_tag(tag, device, connection)
                    if not sent and datetime.now(UTC) >= utc(command.expires_at):
                        raise CommandExpired("Command expired before transmission")
                    registers = (
                        None
                        if type(value) is bool
                        else encode_registers(
                            value,
                            tag.data_type,
                            tag.byte_order,
                            tag.word_order,
                            config.scale,
                            config.offset,
                        )
                    )

                    async def operation(client) -> Reading:
                        nonlocal sent
                        # This callback holds the shared transport lock AND configuration row locks.
                        if not sent:
                            if datetime.now(UTC) >= utc(command.expires_at):
                                raise CommandExpired("Command expired while waiting for transport")
                            sent = True  # Set before awaiting: timeout/cancellation has uncertain outcome.
                            if type(value) is bool:
                                response = await client.write_coil(
                                    tag.address, value, device_id=device.slave_id
                                )
                            elif len(registers) == 1:
                                response = await client.write_register(
                                    tag.address, registers[0], device_id=device.slave_id
                                )
                            else:
                                response = await client.write_registers(
                                    tag.address, registers, device_id=device.slave_id
                                )
                            if response is None or response.isError():
                                raise DecodeError(
                                    "Device rejected the write or returned an invalid acknowledgement"
                                )
                        await self.transition(identifier, "VERIFYING", attempt=attempt)
                        response = await getattr(client, READ_METHODS[tag.register_type])(
                            tag.address,
                            count=1 if type(value) is bool else register_count(tag.data_type),
                            device_id=device.slave_id,
                        )
                        return ModbusSource.decode_response(config, response)

                    # Bounded connection wait and transport I/O; polling continues on other buses.
                    async with asyncio.timeout(connection.timeout_ms / 1000 * 3 + 5):
                        if isinstance(self.source, ModbusSource):
                            reading = await self.source.manager.execute(
                                config.transport, operation, timeout_factor=3
                            )
                        else:
                            if not sent:
                                if self.source.rng.random() < self.source.failure_probability:
                                    raise CommunicationError(
                                        "Simulated command communication failure"
                                    )
                                stored = (
                                    value
                                    if type(value) is bool
                                    else decode_registers(
                                        registers,
                                        tag.data_type,
                                        tag.byte_order,
                                        tag.word_order,
                                        config.scale,
                                        config.offset,
                                    )[0]
                                )
                                self.source.set_control(config, stored)
                                sent = True
                            await self.transition(identifier, "VERIFYING", attempt=attempt)
                            reading = await self.source.read(config)
                    matches = verification_matches(
                        value, reading.value, tag.data_type, config.scale, config.offset
                    )
                    # Serialize against poll persistence and don't replace a newer actual reading.
                    current = await session.scalar(
                        select(TagCurrentValue)
                        .where(TagCurrentValue.tag_id == tag.id)
                        .with_for_update()
                    )
                    if (
                        not current
                        or not current.source_timestamp
                        or utc(current.source_timestamp) <= utc(reading.source_timestamp)
                    ):
                        if current and current.source and current.source != reading.source:
                            await upsert_current(
                                session,
                                tag.id,
                                quality="BAD",
                                error="Telemetry source changed",
                                clear_value=True,
                                history_policy=config,
                            )
                        await upsert_current(
                            session, tag.id, reading=reading, history_policy=config
                        )
                    await session.execute(
                        update(Command)
                        .where(Command.id == identifier)
                        .values(
                            status="SUCCESS" if matches else "FAILED",
                            completed_at=datetime.now(UTC),
                            verified_numeric=reading.value
                            if isinstance(reading.value, Decimal)
                            else None,
                            verified_boolean=reading.value
                            if isinstance(reading.value, bool)
                            else None,
                            error_message=None
                            if matches
                            else f"Read-back mismatch: requested {value}, actual {reading.value}. Write not retried.",
                            revision=Command.revision + 1,
                        )
                    )
                    await notify_command(session, identifier)
                logger.info("Command completed: command_id=%s success=%s", identifier, matches)
                return
            except (CommunicationError, TimeoutError) as exc:
                logger.warning(
                    "Command communication failure: command_id=%s attempt=%s write_may_have_occurred=%s error=%s",
                    identifier,
                    attempt,
                    sent,
                    exc,
                )
                if attempt == self.settings.command_max_attempts:
                    await self.transition(
                        identifier,
                        "FAILED",
                        f"Communication failed after {attempt} attempts. {'Write may have occurred; verification unavailable.' if sent else 'No write sent.'}",
                    )
                    return
                await asyncio.sleep(self.settings.command_retry_seconds * attempt)
            except CommandExpired as exc:
                await self.transition(identifier, "EXPIRED" if not sent else "FAILED", str(exc))
                return
            except (ValueError, DecodeError) as exc:
                await self.transition(identifier, "FAILED", str(exc))
                return
            except Exception:
                logger.exception("Command processing failed: command_id=%s", identifier)
                await self.transition(
                    identifier,
                    "FAILED",
                    "Internal command failure; outcome may be unknown. Inspect actual value before retrying.",
                )
                return

    async def run(self, stop: asyncio.Event) -> None:
        await self.recover()
        while not stop.is_set():
            try:
                identifier = await self.claim()
                if identifier is not None:
                    await self.process(identifier)
                    continue
            except Exception:
                logger.exception("Command queue unavailable; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                pass
