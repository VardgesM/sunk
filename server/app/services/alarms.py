from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AlarmEvent, AlarmRule, NotificationDelivery, Tag, TelegramDestination
from app.schemas.alarms import AlarmInput, AlarmRead, EventRead

ALARM_CHANNEL = "alarm_events_changed"


def rule_read(rule: AlarmRule) -> AlarmRead:
    return AlarmRead(
        **{key: getattr(rule, key) for key in AlarmInput.model_fields if key not in {"value"}},
        value=rule.value_boolean if rule.value_boolean is not None else rule.value_numeric,
        id=rule.id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def fields(payload: AlarmInput) -> dict:
    result = payload.model_dump(exclude={"value"})
    result.update(
        value_boolean=payload.value if type(payload.value) is bool else None,
        value_numeric=payload.value if type(payload.value) is not bool else None,
    )
    return result


async def validate_rule(session: AsyncSession, payload: AlarmInput) -> None:
    tag = await session.get(Tag, payload.tag_id)
    if tag is None:
        raise HTTPException(422, "Tag does not exist")
    if (tag.data_type == "bool") != (type(payload.value) is bool):
        raise HTTPException(422, "Comparison value must match Tag data type")


async def notify_event(session: AsyncSession, event: AlarmEvent) -> None:
    await session.flush()
    if session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": ALARM_CHANNEL, "payload": str(event.id)},
        )


async def get_event(session: AsyncSession, identifier: int) -> EventRead | None:
    event = await session.get(AlarmEvent, identifier)
    return EventRead.model_validate(event) if event else None


def telegram_timestamp(value: datetime, timezone: str) -> str:
    local = value.astimezone(ZoneInfo(timezone))
    return f"{local:%d.%m.%Y %H:%M:%S} ({timezone})"


async def queue_notification(
    session: AsyncSession, event: AlarmEvent, timezone: str = "UTC"
) -> None:
    destination = await session.get(TelegramDestination, 1)
    value = event.value_boolean if event.value_boolean is not None else event.value_numeric
    message = f"{event.severity}\n{event.name}\n{event.tag_name}: {value} {event.unit or ''}\nCondition: {event.condition}\nActivated: {telegram_timestamp(event.activated_at, timezone)}"
    session.add(
        NotificationDelivery(
            event_id=event.id,
            kind="ACTIVATED",
            chat_id=destination.chat_id if destination else None,
            message=message[:4000],
            status="PENDING",
            created_at=datetime.now(UTC),
        )
    )


async def clear_event(session: AsyncSession, event: AlarmEvent, now: datetime, reason: str) -> None:
    event.state, event.cleared_at, event.clear_reason = "CLEARED", now, reason
    event.revision += 1
    await notify_event(session, event)


async def open_event(session: AsyncSession, rule_id: int) -> AlarmEvent | None:
    return await session.scalar(
        select(AlarmEvent)
        .where(AlarmEvent.rule_id == rule_id, AlarmEvent.state != "CLEARED")
        .with_for_update()
    )
