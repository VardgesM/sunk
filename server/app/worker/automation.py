"""Worker rule evaluator. Its only control output is the persistent command queue."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.models import (
    AutomationAction,
    AutomationCondition,
    AutomationExecution,
    AutomationExecutionCommand,
    AutomationRule,
    AutomationRuntime,
    Command,
    Connection,
    Device,
    Tag,
    TagCurrentValue,
)
from app.schemas.telemetry import utc
from app.services.automation import children, value_of
from app.services.automation_evaluation import advance, compare
from app.services.commands import TERMINAL, enqueue_command

logger = logging.getLogger(__name__)


class AutomationEngine:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database, self.settings = database, settings
        self.config: list[
            tuple[AutomationRule, list[AutomationCondition], list[AutomationAction]]
        ] = []
        self.refresh_at: datetime | None = None
        self.observed: dict[int, tuple] = {}
        self.timed: set[int] = set()

    async def recover(self) -> None:
        async with self.database.sessions() as session, session.begin():
            for runtime in await session.scalars(select(AutomationRuntime)):
                runtime.true_since = None
                # Keep consumed edges and hysteresis, but do not count unobserved downtime as FOR.

    async def reconcile(self, session: AsyncSession, now: datetime) -> set[int]:
        changed: set[int] = set()
        events = list(
            await session.scalars(
                select(AutomationExecution)
                .where(AutomationExecution.result == "COMMANDS_CREATED")
                .order_by(AutomationExecution.id)
                .limit(200)
            )
        )
        for event in events:
            commands = list(
                await session.scalars(
                    select(Command)
                    .join(
                        AutomationExecutionCommand,
                        AutomationExecutionCommand.command_id == Command.id,
                    )
                    .where(AutomationExecutionCommand.execution_id == event.id)
                )
            )
            if not commands or any(c.status not in TERMINAL for c in commands):
                continue
            successes = sum(c.status == "SUCCESS" for c in commands)
            event.result = (
                "SUCCESS"
                if successes == len(commands)
                else "PARTIAL_FAILURE"
                if successes
                else "FAILED"
            )
            event.completed_at = max(utc(c.completed_at) for c in commands)
            event.error = (
                "; ".join(f"Command {c.id}: {c.status}" for c in commands if c.status != "SUCCESS")
                or None
            )
            runtime = await session.get(AutomationRuntime, event.rule_id)
            rule = await session.get(AutomationRule, event.rule_id)
            runtime.last_result, runtime.error = event.result, event.error
            changed.add(event.rule_id)
            if event.result == "SUCCESS":
                runtime.cooldown_until = event.completed_at + timedelta(
                    milliseconds=rule.cooldown_ms or 0
                )
                runtime.state = "COOLDOWN" if runtime.cooldown_until > now else "ACTIVE"

        return changed

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        async with self.database.sessions() as session, session.begin():
            candidates = await self.reconcile(session, now)
            candidates.update(self.timed)
            if self.refresh_at is None or now >= self.refresh_at:
                rules = list(
                    await session.scalars(
                        select(AutomationRule).order_by(
                            AutomationRule.priority.desc(), AutomationRule.id
                        )
                    )
                )
                if self.refresh_at is None:
                    candidates.update(r.id for r in rules)
                self.timed.intersection_update(r.id for r in rules)
                versions = {r.id: utc(r.updated_at) for r, _, _ in self.config}
                candidates.update(r.id for r in rules if versions.get(r.id) != utc(r.updated_at))
                self.config = [(r, *(await children(session, r.id))) for r in rules]
                self.refresh_at = now + timedelta(
                    seconds=self.settings.worker_config_refresh_seconds
                )
            ids = {c.tag_id for _, conditions, _ in self.config for c in conditions}
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
            observed = {}
            for tag, device, connection, current in rows:
                fresh = bool(
                    current
                    and current.source_timestamp
                    and (now - utc(current.source_timestamp)).total_seconds() * 1000
                    <= tag.poll_interval_ms * self.settings.stale_multiplier
                )
                observed[tag.id] = (
                    tag.updated_at,
                    device.enabled,
                    connection.enabled,
                    current.revision if current else None,
                    fresh,
                )
            changed_tags = {
                identifier
                for identifier in self.observed.keys() | observed.keys()
                if self.observed.get(identifier) != observed.get(identifier)
            }
            self.observed = observed
            candidates.update(
                rule.id
                for rule, conditions, _ in self.config
                if any(c.tag_id in changed_tags for c in conditions)
            )
        reserved: set[int] = set()
        for cached, conditions, actions in self.config:
            if cached.id not in candidates:
                continue
            try:
                async with self.database.sessions() as session, session.begin():
                    rule = await session.scalar(
                        select(AutomationRule)
                        .where(AutomationRule.id == cached.id)
                        .with_for_update()
                    )
                    if rule is None or utc(rule.updated_at) != utc(cached.updated_at):
                        continue
                    runtime = await session.get(AutomationRuntime, rule.id)
                    snapshot, truths, valid = [], [], True
                    latches = dict(runtime.latches)
                    for condition in conditions:
                        row = inputs.get(condition.tag_id)
                        tag, device, connection, current = row if row else (None, None, None, None)
                        fresh = bool(
                            current
                            and current.source_timestamp
                            and (now - utc(current.source_timestamp)).total_seconds() * 1000
                            <= tag.poll_interval_ms * self.settings.stale_multiplier
                        )
                        source_ok = bool(
                            current
                            and (
                                current.source == "simulator"
                                if self.settings.source_mode == "simulator"
                                else current.source in ("modbus_rtu", "modbus_tcp")
                            )
                        )
                        good = bool(
                            row
                            and tag.enabled
                            and device.enabled
                            and connection.enabled
                            and current
                            and current.quality == "GOOD"
                            and fresh
                            and source_ok
                        )
                        value = (
                            (
                                current.value_boolean
                                if tag.data_type == "bool"
                                else current.value_numeric
                            )
                            if current
                            else None
                        )
                        typed = value is not None and (type(value) is bool) == (
                            type(value_of(condition)) is bool
                        )
                        good = good and typed
                        valid = valid and good
                        snapshot.append(
                            {
                                "tag_id": condition.tag_id,
                                "operator": condition.operator,
                                "comparison": str(value_of(condition))
                                if type(value_of(condition)) is not bool
                                else value_of(condition),
                                "value": str(value) if isinstance(value, Decimal) else value,
                                "quality": current.quality if current else "MISSING",
                            }
                        )
                        if good:
                            state = compare(
                                value,
                                condition.operator,
                                value_of(condition),
                                condition.hysteresis,
                                latches.get(str(condition.id), False),
                            )
                            latches[str(condition.id)] = state
                            truths.append(state)
                    truth = (
                        (all(truths) if rule.condition_mode == "ALL" else any(truths))
                        if valid and truths
                        else None
                    )
                    runtime.latches = latches
                    pending = await session.scalar(
                        select(AutomationExecution.id)
                        .where(
                            AutomationExecution.rule_id == rule.id,
                            AutomationExecution.result == "COMMANDS_CREATED",
                        )
                        .limit(1)
                    )
                    fire = advance(rule, runtime, truth, now, bool(pending))
                    if fire:
                        event = AutomationExecution(
                            rule_id=rule.id,
                            rule_version=rule.updated_at,
                            triggered_at=now,
                            snapshot=snapshot,
                            result="COMMANDS_CREATED",
                        )
                        session.add(event)
                        await session.flush()
                        targets = {a.target_tag_id for a in actions}
                        busy = await session.scalar(
                            select(Command.id)
                            .where(Command.tag_id.in_(targets), Command.status.not_in(TERMINAL))
                            .limit(1)
                        )
                        if targets & reserved or busy:
                            event.result, event.error = (
                                "SKIPPED",
                                "Target reserved by a higher-priority rule or pending command",
                            )
                        else:
                            try:
                                async with session.begin_nested():
                                    rows = (
                                        await session.execute(
                                            select(Tag, Device, Connection)
                                            .join(Device, Device.id == Tag.device_id)
                                            .join(Connection, Connection.id == Device.connection_id)
                                            .where(Tag.id.in_(targets))
                                            .order_by(Tag.id)
                                            .with_for_update(
                                                read=True, of=(Tag, Device, Connection)
                                            )
                                        )
                                    ).all()
                                    target_rows = {r[0].id: r for r in rows}
                                    for action in actions:
                                        if action.target_tag_id not in target_rows:
                                            raise ValueError("Action target no longer exists")
                                        command = await enqueue_command(
                                            session,
                                            *target_rows[action.target_tag_id],
                                            value_of(action),
                                            mode=self.settings.source_mode,
                                            writes_enabled=self.settings.modbus_writes_enabled,
                                            physical_confirmed=self.settings.modbus_writes_enabled,
                                            max_age_seconds=self.settings.command_max_age_seconds,
                                            source="automation",
                                        )
                                        session.add(
                                            AutomationExecutionCommand(
                                                execution_id=event.id, command_id=command.id
                                            )
                                        )
                                reserved.update(targets)
                            except ValueError as exc:
                                event.result, event.error = "FAILED", str(exc)
                        if event.result != "COMMANDS_CREATED":
                            event.completed_at = now
                        runtime.last_result, runtime.error = event.result, event.error
                        if event.error:
                            runtime.state = "ERROR"
                        logger.info(
                            "Automation execution: rule_id=%s result=%s", rule.id, event.result
                        )
                if runtime.state in ("WAITING_FOR_DURATION", "COOLDOWN") or (
                    runtime.armed and runtime.condition_state
                ):
                    self.timed.add(cached.id)
                else:
                    self.timed.discard(cached.id)
            except Exception:
                self.timed.add(cached.id)
                logger.exception("Automation rule evaluation failed: rule_id=%s", cached.id)

    async def run(self, stop: asyncio.Event) -> None:
        await self.recover()
        while not stop.is_set():
            try:
                await self.tick()
            except Exception:
                self.refresh_at = None
                logger.exception("Automation evaluation failed; retrying")
            try:
                await asyncio.wait_for(stop.wait(), 0.25)
            except TimeoutError:
                pass
