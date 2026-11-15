"""Closed set of configuration operations. No URLs, scripts, hardware or credentials."""

import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import alarms, automation, connections, dashboards, devices, locations, tags
from app.db.base import Base
from app.models import (
    AlarmRule,
    AutomationRule,
    Connection,
    Dashboard,
    DashboardWidget,
    Device,
    Location,
    Tag,
)
from app.schemas import configuration as schemas
from app.schemas.alarms import AlarmInput
from app.schemas.automation import RuleInput
from app.schemas.dashboards import DashboardInput, LayoutSave, WidgetInput

RESOURCES = {
    "locations": (
        Location,
        locations,
        "location",
        schemas.LocationCreate,
        schemas.LocationPatch,
        schemas.LocationRead,
    ),
    "connections": (
        Connection,
        connections,
        "connection",
        schemas.ConnectionCreate,
        schemas.ConnectionPatch,
        schemas.ConnectionRead,
    ),
    "devices": (
        Device,
        devices,
        "device",
        schemas.DeviceCreate,
        schemas.DevicePatch,
        schemas.DeviceRead,
    ),
    "tags": (Tag, tags, "tag", schemas.TagCreate, schemas.TagPatch, schemas.TagRead),
    "automation/rules": (AutomationRule, automation),
    "alarms/rules": (AlarmRule, alarms),
    "dashboards": (Dashboard, dashboards),
    "dashboard-widgets": (DashboardWidget, dashboards),
}


@dataclass(frozen=True)
class Operation:
    resource: str
    method: str
    identifier: int | None = None
    child: str | None = None

    @property
    def entity(self) -> str:
        return RESOURCES[self.resource][0].__tablename__

    @property
    def result_entity(self) -> str:
        return "dashboard_widgets" if self.child == "widgets" else self.entity

    @property
    def model(self) -> type[Base]:
        return RESOURCES[self.resource][0]

    def path(self, identifier: int | None = None) -> str:
        result = self.resource
        if self.identifier is not None:
            result += f"/{self.identifier if identifier is None else identifier}"
        return result + (f"/{self.child}" if self.child else "")


def operation(path: str, method: str) -> Operation:
    match = re.fullmatch(
        r"(locations|connections|devices|tags|automation/rules|alarms/rules|dashboards|dashboard-widgets)"
        r"(?:/([1-9][0-9]{0,9}))?(?:/(widgets|layout))?",
        path,
    )
    if not match:
        raise HTTPException(422, "Unsupported remote configuration operation")
    resource, raw, child = match.groups()
    identifier = int(raw) if raw else None
    allowed = (
        method == "POST"
        and identifier is None
        and resource != "dashboard-widgets"
        and not child
        or identifier is not None
        and not child
        and method in ("PATCH", "DELETE", "GET")
        or resource == "dashboards"
        and identifier is not None
        and (child == "widgets" and method == "POST" or child == "layout" and method == "PATCH")
    )
    if not allowed or identifier is not None and identifier > 2147483647:
        raise HTTPException(422, "Unsupported remote configuration operation")
    return Operation(resource, method, identifier, child)


async def execute(session: AsyncSession, op: Operation, data: dict[str, Any]) -> Any:
    """Caller owns lifecycle lock, validation of frozen versions and transaction."""
    if op.resource in ("locations", "connections", "devices", "tags"):
        _, module, singular, create, patch, _ = RESOURCES[op.resource]
        if op.method == "POST":
            return await getattr(module, "create_" + singular)(create.model_validate(data), session)
        if op.method == "PATCH":
            return await getattr(module, "update_" + singular)(
                op.identifier, patch.model_validate(data), session
            )
        return await getattr(module, "delete_" + singular)(op.identifier, session)
    if op.resource == "automation/rules":
        if op.method == "POST":
            return await automation.create_rule(RuleInput.model_validate(data), session)
        if op.method == "PATCH":
            return await automation.patch_rule(op.identifier, session, data)
        return await automation.delete_rule(op.identifier, session)
    if op.resource == "alarms/rules":
        if op.method == "POST":
            return await alarms.create(AlarmInput.model_validate(data), session)
        if op.method == "PATCH":
            return await alarms.patch(op.identifier, session, data)
        return await alarms.remove(op.identifier, session)
    if op.resource == "dashboard-widgets":
        if op.method == "PATCH":
            return await dashboards.patch_widget(op.identifier, session, data)
        return await dashboards.remove_widget(op.identifier, session)
    if op.child == "widgets":
        return await dashboards.create_widget(
            op.identifier, WidgetInput.model_validate(data), session
        )
    if op.child == "layout":
        return await dashboards.save_layout(op.identifier, LayoutSave.model_validate(data), session)
    if op.method == "POST":
        return await dashboards.create(DashboardInput.model_validate(data), session)
    if op.method == "PATCH":
        return await dashboards.patch(op.identifier, session, data)
    return await dashboards.remove(op.identifier, session)


async def read(session: AsyncSession, resource: str, identifier: int) -> dict:
    if resource in ("locations", "connections", "devices", "tags"):
        _, module, singular, _, _, schema = RESOURCES[resource]
        row = await getattr(module, "read_" + singular)(identifier, session)
        return schema.model_validate(row).model_dump(mode="json")
    if resource == "automation/rules":
        row = await automation.read_rule(identifier, session)
    elif resource == "alarms/rules":
        row = await alarms.read(identifier, session)
    elif resource == "dashboard-widgets":
        widget = await dashboards.require_widget(session, identifier)
        row = next(
            w
            for w in await dashboards.widget_reads(session, widget.dashboard_id)
            if w.id == identifier
        )
    else:
        row = await dashboards.read(identifier, session)
    return row.model_dump(mode="json")
