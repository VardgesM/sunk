from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import CurrentValueRead, Quality, utc
from app.services.history_writer import HistoryPolicy, try_write_history

CHANNEL = "tag_current_values_changed"


@dataclass(frozen=True)
class Reading:
    value: Decimal | bool | str
    source_timestamp: datetime
    raw_value: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("Reading must be finite")
        if not isinstance(self.value, (Decimal, bool, str)):
            raise TypeError("Reading must be Decimal, bool, or text")
        if self.source_timestamp.tzinfo is None:
            raise ValueError("Reading timestamp must include a timezone")


async def notify_current(session: AsyncSession, tag_id: int) -> None:
    if session.get_bind().dialect.name == "postgresql":
        # Delivered only on COMMIT, atomically with the row update. No values in the payload.
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": CHANNEL, "payload": str(tag_id)},
        )


async def upsert_current(
    session: AsyncSession,
    tag_id: int,
    *,
    reading: Reading | None = None,
    quality: Quality = "GOOD",
    error: str | None = None,
    clear_value: bool = False,
    now: datetime | None = None,
    history_policy: HistoryPolicy | None = None,
) -> None:
    """Caller owns the transaction. Errors preserve the previous successful value/time."""
    if quality == "GOOD" and (reading is None or error is not None):
        raise ValueError("GOOD requires a reading and no error")
    now = now or datetime.now(UTC)
    fields = {"quality": quality, "error": error, "updated_at": now}
    values = {
        "value_numeric": None,
        "value_boolean": None,
        "value_text": None,
        "raw_value": None,
        "source_timestamp": None,
    }
    if reading is not None:
        column = (
            "value_boolean"
            if isinstance(reading.value, bool)
            else "value_numeric"
            if isinstance(reading.value, Decimal)
            else "value_text"
        )
        values.update(
            {
                column: reading.value,
                "raw_value": reading.raw_value,
                "source_timestamp": reading.source_timestamp,
            }
        )
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    changes = {**fields, "revision": TagCurrentValue.revision + 1}
    if reading is not None or clear_value:
        changes.update(values)
    if reading is not None:
        changes["source"] = reading.source
    elif clear_value:
        changes["source"] = None
    statement = insert(TagCurrentValue).values(
        tag_id=tag_id, revision=1, source=reading.source if reading else None, **fields, **values
    )
    await session.execute(statement.on_conflict_do_update(index_elements=["tag_id"], set_=changes))
    await try_write_history(
        session,
        tag_id,
        quality,
        {**values, "source": reading.source if reading else None},
        now,
        history_policy,
    )
    await notify_current(session, tag_id)


def current_statement() -> Select[tuple[Tag, TagCurrentValue, bool]]:
    return (
        select(
            Tag,
            TagCurrentValue,
            (Tag.enabled & Device.enabled & Connection.enabled).label("effective_enabled"),
        )
        .join(Device, Tag.device_id == Device.id)
        .join(Connection, Device.connection_id == Connection.id)
        .outerjoin(TagCurrentValue, TagCurrentValue.tag_id == Tag.id)
    )


def serialize_current(tag: Tag, current: TagCurrentValue | None, enabled: bool) -> CurrentValueRead:
    fields = (
        {}
        if current is None
        else {
            field: getattr(current, field)
            for field in (
                "value_numeric",
                "value_text",
                "value_boolean",
                "raw_value",
                "quality",
                "source_timestamp",
                "updated_at",
                "error",
                "revision",
                "source",
            )
        }
    )
    return CurrentValueRead(
        tag_id=tag.id,
        key=tag.key,
        name=tag.name,
        device_id=tag.device_id,
        data_type=tag.data_type,
        unit=tag.unit,
        enabled=tag.enabled,
        effective_enabled=enabled,
        **fields,
    )


async def get_current(session: AsyncSession, tag_id: int) -> CurrentValueRead | None:
    row = (await session.execute(current_statement().where(Tag.id == tag_id))).first()
    return serialize_current(*row) if row is not None else None


def is_stale(
    source_timestamp: datetime | None, poll_interval_ms: int, multiplier: float, now: datetime
) -> bool:
    return (
        source_timestamp is not None
        and (utc(now) - utc(source_timestamp)).total_seconds()
        > poll_interval_ms * multiplier / 1000
    )


async def mark_stale(
    session: AsyncSession,
    multiplier: float,
    now: datetime | None = None,
    *,
    write_history: bool = True,
) -> int:
    """Compare-and-set protects a newer GOOD reading against a concurrent stale sweep."""
    now = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(TagCurrentValue, Tag.poll_interval_ms)
            .join(Tag, Tag.id == TagCurrentValue.tag_id)
            .where(TagCurrentValue.quality == "GOOD")
        )
    ).all()
    changed = 0
    for current, interval in rows:
        if not is_stale(current.source_timestamp, interval, multiplier, now):
            continue
        identifier, revision = current.tag_id, current.revision
        result = await session.execute(
            update(TagCurrentValue)
            .where(
                TagCurrentValue.tag_id == identifier,
                TagCurrentValue.revision == revision,
                TagCurrentValue.quality == "GOOD",
            )
            .values(
                quality="STALE",
                updated_at=now,
                error="Expected polling update was not received",
                revision=TagCurrentValue.revision + 1,
            )
        )
        if result.rowcount:
            if write_history:
                await try_write_history(session, identifier, "STALE", {}, now)
            await notify_current(session, identifier)
            changed += 1
    return changed
