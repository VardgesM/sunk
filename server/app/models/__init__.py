"""Shared ORM entities, imported here for Alembic discovery."""

from app.models.alarms import (
    AlarmEvent,
    AlarmRule,
    AlarmRuntime,
    NotificationDelivery,
    TelegramDestination,
)
from app.models.auth import AuditLog, AuthSession, LoginLimit, User
from app.models.backup import ConfigurationIdentity, RecoveryState
from app.models.command import Command
from app.models.configuration import Connection, Device, Location, Tag
from app.models.current_value import TagCurrentValue
from app.models.dashboards import (
    Dashboard,
    DashboardWidget,
    DashboardWidgetLayout,
    DashboardWidgetTag,
)
from app.models.history import TagHistory
from app.models.runtime import ConnectionRuntime, WorkerRuntime
from app.models.sync import (
    EdgeInstallation,
    RemoteInbox,
    RemoteRequest,
    SyncMapping,
    SyncOutbox,
    SyncReceipt,
    SyncState,
)

__all__ = [
    "ConfigurationIdentity",
    "RecoveryState",
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


__all__ += ["Dashboard", "DashboardWidget", "DashboardWidgetTag", "DashboardWidgetLayout"]

__all__ += ["User", "AuthSession", "LoginLimit", "AuditLog"]


__all__ += [
    "SyncState",
    "EdgeInstallation",
    "SyncOutbox",
    "SyncReceipt",
    "SyncMapping",
    "RemoteRequest",
    "RemoteInbox",
]
