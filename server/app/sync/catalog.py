"""Explicit allowlist. Credentials/users/audit/Telegram secrets are NEVER synchronized."""

from app.db.base import Base

# Metadata first so the relational mirror can resolve foreign keys. History has its own lane.
PRIORITIES = {
    "locations": 0,
    "connections": 0,
    "devices": 0,
    "tags": 0,
    "dashboards": 0,
    "dashboard_widgets": 0,
    "dashboard_widget_tags": 0,
    "dashboard_widget_layouts": 0,
    "alarm_rules": 0,
    "automation_rules": 0,
    "automation_conditions": 0,
    "automation_actions": 0,
    "remote_inbox": 1,
    "commands": 1,
    "alarm_events": 2,
    "tag_current_values": 3,
    "connection_runtime": 3,
    "worker_runtime": 3,
    "automation_runtime": 4,
    "automation_executions": 4,
    "automation_execution_commands": 4,
    "tag_history": 9,
}
EXCLUDED = {
    "commands": {"requested_by"},
    "alarm_events": {"acknowledged_by"},
    "worker_runtime": {"hostname", "serial_ports", "discovered_at", "discovery_error"},
}


def table(name: str):
    if name not in PRIORITIES:
        raise ValueError("Unsupported sync entity")
    return Base.metadata.tables[name]


def columns(name: str):
    return [c for c in table(name).columns if c.name not in EXCLUDED.get(name, set())]

# Only replaceable state. Commands, alarm events and history must NEVER enter this set.
CURRENT_ENTITIES = ("tag_current_values",)
STATUS_ENTITIES = ("worker_runtime", "connection_runtime")
COALESCED_ENTITIES = CURRENT_ENTITIES + STATUS_ENTITIES
