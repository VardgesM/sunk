"""History decisions use the indexed last stored row, including after process restarts."""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, TagHistory
from app.schemas.telemetry import utc

logger = logging.getLogger(__name__)


class HistoryPolicy(Protocol):
    history_enabled: bool
    history_mode: str
    history_interval_ms: int | None
    history_change_threshold: float | None


async def write_history(
    session: AsyncSession,
    tag_id: int,
    policy: HistoryPolicy,
    quality: str,
    values: dict,
    now: datetime,
) -> bool:
    if not policy.history_enabled:
        return False
    # No full-history scan or process-local state that can diverge after rollback.
    previous = None
    if quality != "GOOD" or policy.history_mode != "every_sample":
        previous = await session.scalar(
            select(TagHistory)
            .where(TagHistory.tag_id == tag_id)
            .order_by(TagHistory.recorded_at.desc(), TagHistory.id.desc())
            .limit(1)
        )
    if quality != "GOOD":
        if previous is not None and previous.quality == quality:
            return False
        values = {}  # Never copy a retained current value into an outage marker.
    elif previous is not None and previous.quality == "GOOD":
        if policy.history_mode == "fixed_interval":
            if (
                utc(now) - utc(previous.recorded_at)
            ).total_seconds() * 1000 < policy.history_interval_ms:
                return False
        elif policy.history_mode == "on_change":
            numeric = values.get("value_numeric")
            if numeric is not None and previous.value_numeric is not None:
                delta = abs(numeric - previous.value_numeric)
                if delta == 0 or delta < Decimal(str(policy.history_change_threshold)):
                    return False
            elif all(
                values.get(field) == getattr(previous, field)
                for field in ("value_numeric", "value_boolean", "value_text")
            ):
                return False
    await session.execute(
        insert(TagHistory).values(tag_id=tag_id, quality=quality, recorded_at=now, **values)
    )
    return True


async def try_write_history(
    session: AsyncSession,
    tag_id: int,
    quality: str,
    values: dict,
    now: datetime,
    policy: HistoryPolicy | None = None,
) -> None:
    if policy is not None and not policy.history_enabled:
        return
    # A failed history statement rolls back only its savepoint, preserving live state/NOTIFY.
    # PostgreSQL still owns commit/rollback of the outer transaction.
    try:
        async with session.begin_nested():
            if policy is None:
                policy = await session.get(Tag, tag_id)
            if policy is not None and policy.history_enabled:
                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    await session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
                await write_history(session, tag_id, policy, quality, values, now)
    except Exception:
        logger.exception("Tag %s history write failed; current-value update retained", tag_id)
