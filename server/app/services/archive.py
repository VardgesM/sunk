"""Retire operational configuration atomically without erasing retained evidence.

No physical action occurs here. The lifecycle lock waits for an in-flight command;
queued work is cancelled and future work fails the normal enabled/version checks.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmEvent,
    AlarmRule,
    AlarmRuntime,
    AutomationAction,
    AutomationCondition,
    AutomationExecution,
    AutomationExecutionCommand,
    AutomationRule,
    AutomationRuntime,
    Command,
    Connection,
    Dashboard,
    DashboardWidget,
    DashboardWidgetTag,
    Device,
    Location,
    NotificationDelivery,
    Tag,
    TagCurrentValue,
)
from app.services.alarms import clear_event
from app.services.commands import notify_command
from app.services.configuration_lock import lock_configuration_lifecycle
from app.services.current_values import notify_current
from app.services.dashboards import delete_widgets, lock_configuration, touch

ARCHIVABLE = (Location, Connection, Device, Tag, AutomationRule, AlarmRule)


async def archive_configuration(session: AsyncSession, model: type, identifier: int) -> None:
    """Caller commits; repeat DELETE is harmless. Never call after taking row locks."""
    if model not in ARCHIVABLE:
        raise ValueError("Unsupported configuration type")
    await lock_configuration_lifecycle(session, exclusive=True)
    await lock_configuration(session)
    root = await session.get(model, identifier, populate_existing=True)
    if root is None:
        raise HTTPException(404, f"{model.__name__} not found")
    if root.archived_at is not None:
        return
    now = datetime.now(UTC)

    if model is Location:
        # Removing a folder must not disable equipment or silently erase its children.
        await session.execute(
            update(Location)
            .where(
                Location.parent_id == identifier,
                Location.archived_at.is_(None),
            )
            .values(parent_id=root.parent_id, updated_at=now)
        )
        await session.execute(
            update(Device)
            .where(
                Device.location_id == identifier,
                Device.archived_at.is_(None),
            )
            .values(location_id=root.parent_id, updated_at=now)
        )

    devices = []
    if model is Connection:
        devices = list(
            await session.scalars(
                select(Device).where(
                    Device.connection_id == identifier,
                    Device.archived_at.is_(None),
                )
            )
        )
    elif model is Device:
        devices = [root]
    tags = (
        [root]
        if model is Tag
        else list(
            await session.scalars(
                select(Tag).where(
                    Tag.device_id.in_([d.id for d in devices]),
                    Tag.archived_at.is_(None),
                )
            )
        )
        if devices
        else []
    )
    tag_ids = [tag.id for tag in tags]

    automation = list(
        await session.scalars(
            select(AutomationRule).where(
                AutomationRule.archived_at.is_(None),
                or_(
                    AutomationRule.id == (identifier if model is AutomationRule else -1),
                    AutomationRule.id.in_(
                        select(AutomationCondition.rule_id).where(
                            AutomationCondition.tag_id.in_(tag_ids)
                        )
                    ),
                    AutomationRule.id.in_(
                        select(AutomationAction.rule_id).where(
                            AutomationAction.target_tag_id.in_(tag_ids)
                        )
                    ),
                ),
            )
        )
    )
    alarms = list(
        await session.scalars(
            select(AlarmRule).where(
                AlarmRule.archived_at.is_(None),
                or_(
                    AlarmRule.id == (identifier if model is AlarmRule else -1),
                    AlarmRule.tag_id.in_(tag_ids),
                ),
            )
        )
    )
    rule_ids = [rule.id for rule in automation]
    alarm_ids = [rule.id for rule in alarms]

    # Cancel whole pending executions of affected rules, not just the deleted output.
    commands = await session.scalars(
        select(Command)
        .where(
            Command.status == "QUEUED",
            or_(
                Command.tag_id.in_(tag_ids),
                Command.id.in_(
                    select(AutomationExecutionCommand.command_id)
                    .join(
                        AutomationExecution,
                        AutomationExecution.id == AutomationExecutionCommand.execution_id,
                    )
                    .where(AutomationExecution.rule_id.in_(rule_ids))
                ),
            ),
        )
        .with_for_update()
    )
    for command in commands:
        command.status = "CANCELLED"
        command.completed_at = now
        command.error_message = "Configuration deleted; queued command cancelled"
        command.revision += 1
        await notify_command(session, command.id)

    for event in await session.scalars(
        select(AlarmEvent)
        .where(
            AlarmEvent.rule_id.in_(alarm_ids),
            AlarmEvent.state != "CLEARED",
        )
        .with_for_update()
    ):
        await clear_event(session, event, now, "Configuration deleted")
    await session.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.event_id.in_(
                select(AlarmEvent.id).where(AlarmEvent.rule_id.in_(alarm_ids))
            ),
            NotificationDelivery.status == "PENDING",
        )
        .values(status="SKIPPED", completed_at=now, error="Configuration deleted")
    )
    await session.execute(
        update(AlarmRuntime)
        .where(
            AlarmRuntime.rule_id.in_(alarm_ids),
        )
        .values(true_since=None)
    )
    await session.execute(
        update(AutomationRuntime)
        .where(
            AutomationRuntime.rule_id.in_(rule_ids),
        )
        .values(
            state="DISABLED",
            condition_state=False,
            true_since=None,
            armed=False,
            latches={},
            error=None,
        )
    )

    await _detach_widgets(session, tag_ids)
    for record in [root, *devices, *tags, *automation, *alarms]:
        record.archived_at = now
        record.updated_at = now
        if hasattr(record, "enabled"):
            record.enabled = False
    await session.flush()
    await session.execute(delete(TagCurrentValue).where(TagCurrentValue.tag_id.in_(tag_ids)))
    for tag_id in tag_ids:
        await notify_current(session, tag_id)


async def _detach_widgets(session: AsyncSession, tag_ids: list[int]) -> None:
    widgets = list(
        await session.scalars(
            select(DashboardWidget).where(
                DashboardWidget.id.in_(
                    select(DashboardWidgetTag.widget_id).where(
                        DashboardWidgetTag.tag_id.in_(tag_ids)
                    )
                ),
            )
        )
    )
    for widget in widgets:
        await session.execute(
            delete(DashboardWidgetTag).where(
                DashboardWidgetTag.widget_id == widget.id,
                DashboardWidgetTag.tag_id.in_(tag_ids),
            )
        )
        remaining = await session.scalar(
            select(DashboardWidgetTag.tag_id)
            .where(DashboardWidgetTag.widget_id == widget.id)
            .limit(1)
        )
        if remaining is None:
            await delete_widgets(session, [widget.id])
    for dashboard_id in {widget.dashboard_id for widget in widgets}:
        touch(await session.get(Dashboard, dashboard_id))
