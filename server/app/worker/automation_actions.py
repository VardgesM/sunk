"""Plan stateful SET_TAG_VALUE actions; the existing queue performs every write."""

import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    AutomationAction,
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
from app.services.automation import value_of
from app.services.commands import TERMINAL, enqueue_command, validate_write
from app.worker.automation_state import TARGET_ERROR, matches, usable_value

logger = logging.getLogger(__name__)


async def apply_desired_state(
    session: AsyncSession,
    settings: Settings,
    rule: AutomationRule,
    runtime: AutomationRuntime,
    actions: list[AutomationAction],
    snapshot: list[dict],
    now: datetime,
    *,
    initial: bool,
    conflict: bool,
    previous_trigger: datetime | None,
    last_execution: AutomationExecution | None,
    not_before: datetime | None,
) -> None:
    targets = {a.target_tag_id for a in actions}
    busy = await session.scalar(
        select(Command.id)
        .where(Command.tag_id.in_(targets), Command.status.not_in(TERMINAL))
        .limit(1)
    )
    blocked = conflict or busy is not None
    if blocked and not initial:
        return  # Includes equivalent commands and commands requesting another value.
    event = AutomationExecution(
        rule_id=rule.id,
        rule_version=rule.updated_at,
        triggered_at=now,
        snapshot=snapshot,
        result="COMMANDS_CREATED",
    )
    if blocked:
        event.result, event.error = (
            "SKIPPED",
            "Target reserved by a higher-priority rule or pending command",
        )
    else:
        rows = (
            await session.execute(
                select(Tag, Device, Connection)
                .join(Device, Device.id == Tag.device_id)
                .join(Connection, Connection.id == Device.connection_id)
                .where(Tag.id.in_(targets))
                .order_by(Tag.id)
                .with_for_update(read=True, of=(Tag, Device, Connection))
            )
        ).all()
        by_id = {r[0].id: r for r in rows}
        currents = {
            v.tag_id: v
            for v in await session.scalars(
                select(TagCurrentValue)
                .where(TagCurrentValue.tag_id.in_(targets))
                .order_by(TagCurrentValue.tag_id)
                .with_for_update()
            )
        }
        selected: list[AutomationAction] = []
        details: list[dict] = []
        unavailable = False
        try:
            for action in actions:
                if action.kind != "SET_TAG_VALUE":
                    raise ValueError("Only stateful SET_TAG_VALUE actions can be reconciled")
                if action.target_tag_id not in by_id:
                    raise ValueError("Action target no longer exists")
                tag, device, connection = by_id[action.target_tag_id]
                desired = value_of(action)
                validate_write(tag, device, connection, desired)
                current = currents.get(tag.id)
                actual = usable_value(tag, device, connection, current, settings, now)
                configured_at = max(utc(row.updated_at) for row in (tag, device, connection))
                if (
                    actual is None
                    or utc(current.source_timestamp) < configured_at
                    or (not_before and utc(current.source_timestamp) < not_before)
                ):
                    unavailable = True
                    continue
                matched = matches(tag, desired, actual)
                # A stale poll captured before the last completion cannot undo verified success.
                if (
                    not matched
                    and not initial
                    and last_execution
                    and last_execution.completed_at
                    and utc(current.source_timestamp) <= utc(last_execution.completed_at)
                ):
                    unavailable = True
                    continue
                if not matched:
                    selected.append(action)
                details.append(
                    {
                        "kind": "desired_state",
                        "reason": "already_desired"
                        if matched
                        else "initial"
                        if initial
                        else "reconciliation",
                        "tag_id": tag.id,
                        "operator": "==",
                        "comparison": str(desired) if isinstance(desired, Decimal) else desired,
                        "value": str(actual) if isinstance(actual, Decimal) else actual,
                        "quality": current.quality,
                        "revision": current.revision,
                    }
                )
            if unavailable:
                if initial:
                    # Wait for readable outputs without consuming the initial edge.
                    runtime.armed, runtime.last_triggered_at = True, previous_trigger
                runtime.state, runtime.error = "ERROR", TARGET_ERROR
                return
            if not selected and not initial:
                return  # No repeated executions/logging for normal matched state.
            event.snapshot = snapshot + details
            session.add(event)
            await session.flush()
            async with session.begin_nested():
                for action in selected:
                    command = await enqueue_command(
                        session,
                        *by_id[action.target_tag_id],
                        value_of(action),
                        mode=settings.source_mode,
                        writes_enabled=settings.modbus_writes_enabled,
                        physical_confirmed=settings.modbus_writes_enabled,
                        max_age_seconds=settings.command_max_age_seconds,
                        source="automation",
                    )
                    session.add(
                        AutomationExecutionCommand(execution_id=event.id, command_id=command.id)
                    )
            if not selected:
                event.result = "SUCCESS"  # First activation was already satisfied; no I/O required.
            for detail in details:
                if detail["reason"] == "already_desired":
                    continue
                logger.info(
                    "Automation reconciliation mismatch: rule_id=%s target=%s desired=%s actual=%s",
                    rule.id,
                    detail["tag_id"],
                    detail["comparison"],
                    detail["value"],
                )
        except ValueError as exc:
            event.result, event.error = "FAILED", str(exc)
    session.add(event)
    if event.result != "COMMANDS_CREATED":
        event.completed_at = now
    runtime.last_triggered_at = now
    runtime.last_result, runtime.error = event.result, event.error
    if event.error:
        runtime.state = "ERROR"
    logger.info("Automation execution: rule_id=%s result=%s", rule.id, event.result)
