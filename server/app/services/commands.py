from decimal import Decimal

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Command, Connection, Device, Tag
from app.schemas.commands import CommandRead
from app.services.encoding import encode_registers, verification_matches
from app.worker.decoder import decode_registers

COMMAND_CHANNEL = "commands_changed"
TERMINAL = {"SUCCESS", "FAILED", "CANCELLED", "EXPIRED"}


async def notify_command(session: AsyncSession, identifier: int) -> None:
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_notify(:channel, :id)"),
            {"channel": COMMAND_CHANNEL, "id": str(identifier)},
        )


def validate_write(tag: Tag, device: Device, connection: Connection, value: Decimal | bool) -> None:
    if not (tag.enabled and device.enabled and connection.enabled):
        raise ValueError("Tag, Device and Connection must all be enabled")
    if not tag.writable or tag.register_type not in ("coil", "holding_register"):
        raise ValueError("Tag must be writable and use coil or holding_register")
    boolean = tag.register_type == "coil"
    if boolean != (type(value) is bool):
        raise ValueError("Coils require a JSON boolean; registers require a numeric value")
    numeric = Decimal(int(value)) if boolean else value
    if tag.min_value is not None and numeric < Decimal(str(tag.min_value)):
        raise ValueError("Requested value is below the configured minimum")
    if tag.max_value is not None and numeric > Decimal(str(tag.max_value)):
        raise ValueError("Requested value is above the configured maximum")
    if not boolean:
        registers = encode_registers(
            value,
            tag.data_type,
            tag.byte_order,
            tag.word_order,
            Decimal(str(tag.scale)),
            Decimal(str(tag.offset)),
        )
        representable, _ = decode_registers(
            registers,
            tag.data_type,
            tag.byte_order,
            tag.word_order,
            Decimal(str(tag.scale)),
            Decimal(str(tag.offset)),
        )
        if (tag.min_value is not None and representable < Decimal(str(tag.min_value))) or (
            tag.max_value is not None and representable > Decimal(str(tag.max_value))
        ):
            raise ValueError("Encoded value would exceed configured limits after float rounding")
        if not verification_matches(
            value, representable, tag.data_type, Decimal(str(tag.scale)), Decimal(str(tag.offset))
        ):
            raise ValueError(
                "Requested engineering value cannot be represented within verification precision"
            )


def command_value(command: Command, prefix: str) -> Decimal | bool | None:
    numeric = getattr(command, prefix + "_numeric")
    return numeric if numeric is not None else getattr(command, prefix + "_boolean")


def serialize_command(command: Command, tag: Tag, device: Device) -> CommandRead:
    return CommandRead(
        **{
            name: getattr(command, name)
            for name in (
                "id",
                "request_id",
                "tag_id",
                "status",
                "source",
                "telemetry_mode",
                "attempt_count",
                "revision",
                "created_at",
                "expires_at",
                "started_at",
                "completed_at",
                "error_message",
            )
        },
        tag_name=tag.name,
        device_id=device.id,
        device_name=device.name,
        requested_value=command_value(command, "requested"),
        previous_value=command_value(command, "previous"),
        verified_value=command_value(command, "verified"),
    )


def command_query() -> Select[tuple[Command, Tag, Device]]:
    return (
        select(Command, Tag, Device)
        .join(Tag, Tag.id == Command.tag_id)
        .join(Device, Device.id == Tag.device_id)
    )


async def get_command(session: AsyncSession, identifier: int) -> CommandRead | None:
    row = (await session.execute(command_query().where(Command.id == identifier))).first()
    return serialize_command(*row) if row else None
