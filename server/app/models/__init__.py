"""Shared ORM entities, imported here for Alembic discovery."""

from app.models.alarms import (
    AlarmEvent,
    AlarmRule,
    AlarmRuntime,
    NotificationDelivery,
    TelegramDestination,
)
from app.models.command import Command
from app.models.configuration import Connection, Device, Location, Tag
from app.models.current_value import TagCurrentValue
from app.models.history import TagHistory
from app.models.runtime import ConnectionRuntime, WorkerRuntime

__all__ = [
    "Command",
    "Connection",
    "Device",
    "Location",
    "Tag",
    "TagCurrentValue",
    "TagHistory",
    "ConnectionRuntime",
    "WorkerRuntime",
]

from app.models.automation import (
    AutomationAction,
    AutomationCondition,
    AutomationExecution,
    AutomationExecutionCommand,
    AutomationRule,
    AutomationRuntime,
)

__all__ += [
    "AutomationRule",
    "AutomationCondition",
    "AutomationAction",
    "AutomationRuntime",
    "AutomationExecution",
    "AutomationExecutionCommand",
]


__all__ += [
    "AlarmRule",
    "AlarmRuntime",
    "AlarmEvent",
    "TelegramDestination",
    "NotificationDelivery",
]
