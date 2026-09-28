"""Strict relational mirror with per-installation mappings and monotonic revisions."""

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlarmEvent,
    Command,
    EdgeInstallation,
    RemoteRequest,
    SyncMapping,
    SyncReceipt,
)
from app.services.alarms import notify_event
from app.services.commands import notify_command
from app.services.current_values import notify_current
from app.sync.catalog import COALESCED_ENTITIES, columns, table
from app.sync.protocol import Event


class DependencyPending(ValueError):
    pass


def local_key(entity: str, payload: dict) -> str:
    return json.dumps(
        {c.name: payload[c.name] for c in table(entity).primary_key},
        sort_keys=True,
        separators=(",", ":"),
    )


def identity(edge_id: str, entity: str, key: str) -> str:
    return str(uuid5(UUID(edge_id), entity + ":" + key))


def values(entity: str, payload: dict) -> dict:
    allowed = {c.name: c for c in columns(entity)}
    if set(payload) != set(allowed):
        raise ValueError("Sync row does not match version 1 schema")
    result = {}
    for name, column in allowed.items():
        value = payload[name]
        if value is None:
            if not column.nullable:
                raise ValueError("Null in required field")
        elif isinstance(column.type, Boolean):
            if type(value) is not bool:
                raise ValueError("Expected boolean")
        elif isinstance(column.type, Integer):
            if type(value) is not int:
                raise ValueError("Expected integer")
        elif isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
            if value.tzinfo is None:
                raise ValueError("Timestamp requires UTC offset")
        elif isinstance(column.type, (Numeric, Float)):
            value = Decimal(str(value))
            if not value.is_finite():
                raise ValueError("Nonfinite numeric")
            if isinstance(column.type, Float):
                value = float(value)
        elif isinstance(column.type, String):
            if not isinstance(value, str) or column.type.length and len(value) > column.type.length:
                raise ValueError("Invalid string")
        result[name] = value
    return result


async def mapping_for(
    session: AsyncSession, edge_id: str, entity: str, key: str
) -> SyncMapping | None:
    return await session.get(SyncMapping, identity(edge_id, entity, key))


async def apply_event(session: AsyncSession, edge: EdgeInstallation, event: Event) -> None:
    durable = event.entity not in COALESCED_ENTITIES
    if durable and await session.get(SyncReceipt, (edge.id, str(event.event_id))):
        return
    data = values(event.entity, event.payload)
    if event.entity == "worker_runtime":
        # Last source timestamp wins over replayed worker heartbeats.
        old = edge.runtime.get("heartbeat_at")
        if not old or datetime.fromisoformat(old) < data["heartbeat_at"]:
            edge.runtime = event.payload
    elif event.entity == "remote_inbox":
        from app.sync.remote import receive_result

        await receive_result(session, edge, event.payload)
    else:
        await apply_row(session, edge, event, data)
    if durable:
        session.add(SyncReceipt(edge_id=edge.id, event_id=str(event.event_id)))
    await session.flush()


async def apply_row(
    session: AsyncSession, edge: EdgeInstallation, event: Event, data: dict
) -> None:
    entity = event.entity
    target = table(entity)
    key = local_key(entity, event.payload)
    mapping = await mapping_for(session, edge.id, entity, key)
    if mapping and mapping.sequence >= event.sequence:
        return
    if mapping is None:
        mapping = SyncMapping(
            id=identity(edge.id, entity, key),
            edge_id=edge.id,
            entity=entity,
            local_key=key,
            cloud_key={},
            sequence=0,
            original={},
        )
        session.add(mapping)
    if event.operation == "delete":
        if not mapping.cloud_key:
            if entity in COALESCED_ENTITIES:
                # The unsent insert may have been replaced by a delete. Retain its
                # sequence tombstone so an older in-flight value cannot resurrect it.
                mapping.sequence = event.sequence
                mapping.original = event.payload
                mapping.deleted = True
                await session.flush()
                return
            raise DependencyPending("Prior metadata not received")
        if entity in (
            "locations",
            "connections",
            "devices",
            "tags",
            "alarm_rules",
            "automation_rules",
        ):
            # Cloud retains historical references after Edge retention/deletion. Keep a tombstone.
            if "enabled" in target.c:
                await session.execute(
                    update(target)
                    .where(*[target.c[k] == v for k, v in mapping.cloud_key.items()])
                    .values(enabled=False)
                )
        else:
            await session.execute(
                delete(target).where(*[target.c[k] == v for k, v in mapping.cloud_key.items()])
            )
        mapping.deleted = True
    else:
        for column in target.columns:
            if column.name not in data or data[column.name] is None:
                continue
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent == "users":
                    continue
                refkey = json.dumps(
                    {fk.column.name: data[column.name]}, sort_keys=True, separators=(",", ":")
                )
                ref = await mapping_for(session, edge.id, parent, refkey)
                if ref is None or not ref.cloud_key:
                    raise DependencyPending("Referenced metadata not received")
                data[column.name] = ref.cloud_key[fk.column.name]
        if entity == "tags":
            data["key"] = event.payload["key"][:42] + "_" + UUID(mapping.id).hex[:20]
        if entity == "dashboards":
            data["slug"] = "edge-" + UUID(mapping.id).hex
            data["name"] = (edge.name + " / " + data["name"])[:200]
            # Cloud default is deterministic first imported dashboard, not competing Edge defaults.
            data["is_default"] = False
        if entity == "commands":
            request = await session.get(RemoteRequest, event.payload["request_id"])
            if request and request.edge_id == edge.id and request.kind == "command":
                existing = await session.get(Command, request.command_id)
                if existing.tag_id != data["tag_id"]:
                    raise ValueError("Remote command target mismatch")
                mapping.cloud_key = {"id": existing.id}
                mapping.cloud_id = existing.id
                data["requested_by"] = existing.requested_by
                data["requested_by_username"] = existing.requested_by_username
                request.status = data["status"]
                request.error = data["error_message"]
                request.completed_at = data["completed_at"]
            else:
                data["request_id"] = str(uuid5(UUID(edge.id), data["request_id"]))
        if mapping.cloud_key:
            pk = mapping.cloud_key
            if entity in ("tag_current_values", "commands", "alarm_events"):
                previous = await session.scalar(
                    select(target.c.revision).where(*[target.c[k] == v for k, v in pk.items()])
                )
                data["revision"] = max(data["revision"], (previous or 0) + 1)
            result = await session.execute(
                update(target)
                .where(*[target.c[k] == v for k, v in pk.items()])
                .values(**{k: v for k, v in data.items() if k not in pk})
            )
            if result.rowcount == 0:
                # Layout/binding composite keys may be removed and recreated by an edit.
                await session.execute(insert(target).values(**(data | pk)))
        else:
            if "id" in target.c and target.c.id.primary_key:
                data.pop("id", None)
            result = await session.execute(
                insert(target).values(**data).returning(*target.primary_key)
            )
            mapping.cloud_key = dict(result.mappings().one())
            mapping.cloud_id = mapping.cloud_key.get("id")
        mapping.deleted = False
    mapping.sequence = event.sequence
    mapping.original = event.payload
    await session.flush()
    if entity == "tag_current_values":
        await notify_current(session, mapping.cloud_key["tag_id"])
    elif entity == "commands":
        await notify_command(session, mapping.cloud_key["id"])
    elif entity == "alarm_events":
        alarm = await session.get(AlarmEvent, mapping.cloud_key["id"], populate_existing=True)
        if alarm:
            await notify_event(session, alarm)
