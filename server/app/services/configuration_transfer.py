"""Portable, allowlisted configuration graph. Caller owns the single transaction."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmRule,
    AlarmRuntime,
    AutomationRule,
    AutomationRuntime,
    ConfigurationIdentity,
    Connection,
    Dashboard,
    DashboardWidget,
    Device,
    Location,
    Tag,
)
from app.schemas.alarms import AlarmInput
from app.schemas.automation import RuleInput
from app.schemas.backup import APP_VERSION, ConfigurationData, ConfigurationDocument, PortableObject
from app.schemas.configuration import ConnectionCreate, DeviceCreate, LocationCreate, TagCreate
from app.schemas.dashboards import DashboardInput, WidgetInput
from app.services import alarms, automation, dashboards
from app.services.backup_archive import BackupError

ENTITIES = {
    "locations": (Location, LocationCreate),
    "connections": (Connection, ConnectionCreate),
    "devices": (Device, DeviceCreate),
    "tags": (Tag, TagCreate),
    "dashboards": (Dashboard, DashboardInput),
    "widgets": (DashboardWidget, WidgetInput),
    "automation_rules": (AutomationRule, RuleInput),
    "alarm_rules": (AlarmRule, AlarmInput),
}
REFERENCES = {
    "parent_id": "locations",
    "location_id": "locations",
    "connection_id": "connections",
    "device_id": "devices",
    "tag_id": "tags",
    "target_tag_id": "tags",
    "dashboard_id": "dashboards",
}


async def lock_configuration(session: AsyncSession) -> None:
    if session.bind.dialect.name == "postgresql":
        # Blocks concurrent configuration mutations, not telemetry/current/history tables.
        await session.execute(text("SELECT pg_advisory_xact_lock(927009)"))
        await session.execute(
            text(
                "LOCK TABLE locations, connections, devices, tags, dashboards, "
                "dashboard_widgets, dashboard_widget_tags, dashboard_widget_layouts, automation_rules, "
                "automation_conditions, automation_actions, alarm_rules, configuration_identities "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )


def remap(values: dict, lookup) -> dict:
    result = {}
    for key, value in values.items():
        if key in REFERENCES and value is not None:
            result[key] = lookup(REFERENCES[key], value)
        elif key == "tag_ids":
            if not isinstance(value, list) or len(value) > 8:
                raise BackupError("Widget tag_ids must be a list of at most eight references")
            result[key] = [lookup("tags", item) for item in value]
        elif key in ("conditions", "actions"):
            if (
                not isinstance(value, list)
                or len(value) > 100
                or any(not isinstance(item, dict) for item in value)
            ):
                raise BackupError("Conditions/actions must be lists of at most 100 objects")
            result[key] = [remap(item, lookup) for item in value]
        else:
            result[key] = value
    return result


async def export_configuration(session: AsyncSession) -> ConfigurationDocument:
    await lock_configuration(session)
    identities = {
        (r.entity, r.local_id): r.id for r in await session.scalars(select(ConfigurationIdentity))
    }
    rows = {
        name: list(await session.scalars(select(model).order_by(model.id)))
        for name, (model, _) in ENTITIES.items()
    }
    for entity, records in rows.items():
        for row in records:
            if (entity, row.id) not in identities:
                public = str(uuid4())
                session.add(ConfigurationIdentity(id=public, entity=entity, local_id=row.id))
                identities[entity, row.id] = public
    widget_data = {}
    for dashboard in rows["dashboards"]:
        widget_data.update({w.id: w for w in await dashboards.widget_reads(session, dashboard.id)})
    output = {}
    for entity, records in rows.items():
        schema = ENTITIES[entity][1]
        output[entity] = []
        for row in records:
            if entity == "widgets":
                data = widget_data[row.id].model_dump(
                    mode="json", include=set(schema.model_fields) | {"dashboard_id"}
                )
            elif entity == "automation_rules":
                data = (await automation.rule_read(session, row)).model_dump(
                    mode="json", include=set(schema.model_fields)
                )
            elif entity == "alarm_rules":
                data = alarms.rule_read(row).model_dump(
                    mode="json", include=set(schema.model_fields)
                )
            else:
                data = schema.model_validate(
                    {key: getattr(row, key) for key in schema.model_fields}
                ).model_dump(mode="json")
            output[entity].append(
                PortableObject(
                    id=identities[entity, row.id],
                    values=remap(data, lambda kind, key: identities[kind, key]),
                )
            )
    return ConfigurationDocument(
        exported_at=datetime.now(UTC),
        application_version=APP_VERSION,
        data=ConfigurationData(**output),
    )


def ordered_locations(items: list[PortableObject]) -> list[PortableObject]:
    pending = {str(item.id): item for item in items}
    ordered, visited = [], set()
    while pending:
        ready = [
            key
            for key, item in pending.items()
            if item.values.get("parent_id") is None or item.values.get("parent_id") in visited
        ]
        if not ready:
            raise BackupError("Locations contain a cycle or an unknown parent identifier")
        for key in ready:
            ordered.append(pending.pop(key))
            visited.add(key)
    return ordered


async def import_configuration(
    session: AsyncSession, document: ConfigurationDocument
) -> dict[str, int]:
    await lock_configuration(session)
    groups = {key: getattr(document.data, key) for key in ENTITIES}
    identifiers = [str(item.id) for items in groups.values() for item in items]
    if len(identifiers) > 20000 or len(set(identifiers)) != len(identifiers):
        raise BackupError("Too many objects or duplicate stable identifiers")
    # Query in bounded chunks; also works with SQLite's parameter limit in isolated tests.
    for start in range(0, len(identifiers), 500):
        if await session.scalar(
            select(ConfigurationIdentity.id)
            .where(ConfigurationIdentity.id.in_(identifiers[start : start + 500]))
            .limit(1)
        ):
            raise BackupError(
                "Stable identifier conflict: this configuration was already imported/exported here"
            )
    for entity, keys in {
        "tags": ["key"],
        "dashboards": ["slug"],
        "connections": ["name"],
        "automation_rules": ["name"],
        "alarm_rules": ["name"],
    }.items():
        model = ENTITIES[entity][0]
        for key in keys:
            existing = set(await session.scalars(select(getattr(model, key))))
            incoming = [item.values.get(key) for item in groups[entity]]
            if any(not isinstance(value, str) or not value.strip() for value in incoming):
                raise BackupError(f"Invalid {entity}.{key}; a non-empty string is required")
            if len(set(incoming)) != len(incoming) or existing.intersection(incoming):
                raise BackupError(
                    f"Conflict in {entity}.{key}; rename the source configuration before importing"
                )
    if any(item.values.get("is_default") for item in groups["dashboards"]) and await session.scalar(
        select(Dashboard.id).where(Dashboard.is_default).limit(1)
    ):
        raise BackupError("A default dashboard already exists")
    groups["locations"] = ordered_locations(groups["locations"])
    mapped: dict[tuple[str, str], int] = {}

    def lookup(kind: str, identifier: object) -> int:
        try:
            return mapped[kind, str(UUID(str(identifier)))]
        except (ValueError, KeyError):
            raise BackupError(f"Unknown or incompatible {kind} reference") from None

    for entity, items in groups.items():
        model, schema = ENTITIES[entity]
        for item in items:
            data = remap(item.values, lookup)
            dashboard_id = data.pop("dashboard_id", None) if entity == "widgets" else None
            payload = schema.model_validate(data)
            fields = payload.model_dump()
            if entity == "connections":
                fields["enabled"] = False
            if entity == "automation_rules":
                await automation.validate_rule(session, payload, require_enabled=False)
                fields = payload.model_dump(exclude={"conditions", "actions"})
                fields["enabled"] = False
            if entity == "alarm_rules":
                await alarms.validate_rule(session, payload)
                fields = alarms.fields(payload)
                fields.update(enabled=False, notification_enabled=False)
            if entity == "widgets":
                if dashboard_id is None:
                    raise BackupError("Widget requires a dashboard reference")
                await dashboards.validate_tags(session, payload, require_enabled=False)
                fields = payload.model_dump(exclude={"tag_ids", "layouts"})
                fields["dashboard_id"] = dashboard_id
            row = model(**fields)
            session.add(row)
            await session.flush()
            mapped[entity, str(item.id)] = row.id
            session.add(ConfigurationIdentity(id=str(item.id), entity=entity, local_id=row.id))
            if entity == "automation_rules":
                automation.add_children(session, row.id, payload)
                session.add(AutomationRuntime(rule_id=row.id, state="DISABLED"))
            elif entity == "alarm_rules":
                session.add(AlarmRuntime(rule_id=row.id))
            elif entity == "widgets":
                await dashboards.replace_children(session, row, payload)
    await session.flush()
    return {key: len(items) for key, items in groups.items()}
