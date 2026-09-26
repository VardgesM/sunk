"""Read-only alarm evaluator, independent from automation and control commands."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import Settings
from app.db.session import Database
from app.models import AlarmEvent, AlarmRule, AlarmRuntime, Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import utc
from app.services.alarms import clear_event, notify_event, open_event, queue_notification
from app.services.automation_evaluation import compare

logger = logging.getLogger(__name__)


class AlarmEngine:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database, self.settings = database, settings
        self.config: list[AlarmRule] = []
        self.refresh_at: datetime | None = None
        self.observed: dict[int, tuple] = {}
        self.timed: set[int] = set()

    async def recover(self) -> None:
        async with self.database.sessions() as session, session.begin():
            await session.execute(update(AlarmRuntime).values(true_since=None))

    def valid(self, row, now: datetime) -> bool:
        tag, device, connection, current = row
        return bool(
            self.settings.source_mode != "disabled"
            and tag.enabled
            and device.enabled
            and connection.enabled
            and current
            and current.quality == "GOOD"
            and current.source_timestamp
            and 0
            <= (now - utc(current.source_timestamp)).total_seconds() * 1000
            <= tag.poll_interval_ms * self.settings.stale_multiplier
            and current.source
            == ("simulator" if self.settings.source_mode == "simulator" else connection.protocol)
        )

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        async with self.database.sessions() as session:
            changed = set(self.timed)
            if self.refresh_at is None or now >= self.refresh_at:
                rules = list(
                    await session.scalars(
                        select(AlarmRule).where(AlarmRule.enabled).order_by(AlarmRule.id)
                    )
                )
                versions = {r.id: r.updated_at for r in self.config}
                changed.update(r.id for r in rules if versions.get(r.id) != r.updated_at)
                self.config = rules
                self.timed.intersection_update(r.id for r in rules)
                self.refresh_at = now + timedelta(
                    seconds=self.settings.worker_config_refresh_seconds
                )
            ids = {r.tag_id for r in self.config}
            rows = (
                (
                    await session.execute(
                        select(Tag, Device, Connection, TagCurrentValue)
                        .join(Device, Device.id == Tag.device_id)
                        .join(Connection, Connection.id == Device.connection_id)
                        .outerjoin(TagCurrentValue, TagCurrentValue.tag_id == Tag.id)
                        .where(Tag.id.in_(ids))
                    )
                ).all()
                if ids
                else []
            )
            inputs = {r[0].id: r for r in rows}
            observed = {
                r[0].id: (
                    r[0].updated_at,
                    r[1].enabled,
                    r[2].enabled,
                    r[3].revision if r[3] else None,
                    self.valid(r, now),
                )
                for r in rows
            }
            changed.update(
                r.id for r in self.config if observed.get(r.tag_id) != self.observed.get(r.tag_id)
            )
            self.observed = observed
        for cached in self.config:
            if cached.id not in changed:
                continue
            try:
                async with self.database.sessions() as session, session.begin():
                    rule = await session.scalar(
                        select(AlarmRule).where(AlarmRule.id == cached.id).with_for_update()
                    )
                    if not rule or not rule.enabled or rule.updated_at != cached.updated_at:
                        continue
                    runtime = await session.get(AlarmRuntime, rule.id)
                    event = await open_event(session, rule.id)
                    row = inputs.get(rule.tag_id)
                    self.timed.discard(rule.id)
                    if not row or not self.valid(row, now):
                        runtime.true_since = None
                        continue
                    tag, _, _, current = row
                    value = (
                        current.value_boolean if tag.data_type == "bool" else current.value_numeric
                    )
                    threshold = (
                        rule.value_boolean if rule.value_boolean is not None else rule.value_numeric
                    )
                    if value is None or (type(value) is bool) != (type(threshold) is bool):
                        runtime.true_since = None
                        continue
                    truth = compare(
                        value, rule.operator, threshold, rule.hysteresis, event is not None
                    )
                    if not truth:
                        runtime.true_since = None
                        if event:
                            await clear_event(session, event, now, "Condition cleared")
                        continue
                    if event:
                        continue
                    runtime.true_since = runtime.true_since or now
                    if (now - utc(runtime.true_since)).total_seconds() * 1000 < (
                        rule.for_duration_ms or 0
                    ):
                        self.timed.add(rule.id)
                        continue
                    event = AlarmEvent(
                        rule_id=rule.id,
                        tag_id=tag.id,
                        name=rule.name,
                        tag_name=tag.name,
                        unit=tag.unit,
                        condition=f"{rule.operator} {threshold} {tag.unit or ''}".strip(),
                        severity=rule.severity,
                        state="ACTIVE",
                        value_boolean=value if type(value) is bool else None,
                        value_numeric=value if type(value) is not bool else None,
                        activated_at=now,
                    )
                    session.add(event)
                    await notify_event(session, event)
                    if rule.notification_enabled:
                        await queue_notification(session, event, self.settings.telegram_timezone)
                    runtime.true_since = None
            except Exception:
                self.timed.add(cached.id)
                logger.exception("Alarm evaluation failed; rule_id=%s", cached.id)

    async def run(self, stop: asyncio.Event) -> None:
        recovered = False
        while not stop.is_set():
            try:
                if not recovered:
                    await self.recover()
                    recovered = True
                await self.tick()
            except Exception:
                logger.exception("Alarm engine failed; retrying")
            try:
                await asyncio.wait_for(stop.wait(), 0.25)
            except TimeoutError:
                pass
