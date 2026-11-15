"""Cloud validates and queues configuration intent; only Edge mutates configuration."""

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EdgeInstallation, RemoteRequest, SyncMapping
from app.schemas.telemetry import utc
from app.sync.configuration_dispatch import operation, read
from app.sync.mirror import identity

CAPABILITY = "configuration-v1"


class ConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    edge_id: UUID | None = None
    method: Literal["POST", "PATCH", "DELETE"]
    path: str = Field(max_length=120)
    payload: dict = Field(default_factory=dict)
    expected_updated_at: datetime | None = None

    @field_validator("expected_updated_at")
    @classmethod
    def timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Configuration version needs a UTC offset")
        return value


async def mapping(session: AsyncSession, entity: str, identifier: int) -> SyncMapping:
    if type(identifier) is not int or identifier <= 0:
        raise HTTPException(422, "Invalid configuration reference")
    row = await session.scalar(
        select(SyncMapping).where(
            SyncMapping.entity == entity, SyncMapping.cloud_id == identifier, ~SyncMapping.deleted
        )
    )
    if row is None or row.original.get("archived_at"):
        raise HTTPException(409, "Configuration is unavailable or not synchronized from Edge")
    return row


def references(data: dict[str, Any]) -> Iterator[tuple[dict | list, str | int, str]]:
    """Yield only relational fields, never IDs inside arbitrary widget text/settings."""
    fields = {
        "parent_id": "locations",
        "connection_id": "connections",
        "location_id": "locations",
        "device_id": "devices",
        "tag_id": "tags",
        "target_tag_id": "tags",
        "widget_id": "dashboard_widgets",
    }
    for key, entity in fields.items():
        if key in data and data[key] is not None:
            yield data, key, entity
    if "tag_ids" in data:
        if not isinstance(data["tag_ids"], list):
            raise HTTPException(422, "Tag bindings must be a list")
        for index in range(len(data["tag_ids"])):
            yield data["tag_ids"], index, "tags"
    for key in ("conditions", "actions", "layouts"):
        if key in data:
            if not isinstance(data[key], list) or any(not isinstance(v, dict) for v in data[key]):
                raise HTTPException(422, "Invalid configuration children")
            for item in data[key]:
                yield from references(item)


async def enqueue(
    session: AsyncSession, request: Request, payload: ConfigurationRequest
) -> RemoteRequest:
    if request.app.state.settings.application_mode != "cloud":
        raise HTTPException(409, "Remote configuration is available on Cloud")
    if request.state.user.role != "ADMIN":
        raise HTTPException(403, "Administrator permission required")
    if len(payload.model_dump_json()) > 200_000:
        raise HTTPException(413, "Configuration request too large")
    op = operation(payload.path, payload.method)
    if op.method == "DELETE" and payload.payload:
        raise HTTPException(422, "DELETE must not contain configuration values")
    fingerprint = hashlib.sha256(
        json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    # Serializes duplicate request IDs without replaying a concurrent enqueue.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int.from_bytes(payload.request_id.bytes[:8], signed=True)},
        )
    existing = await session.get(RemoteRequest, str(payload.request_id))
    if existing:
        if (
            existing.kind != "configuration"
            or existing.user_id != request.state.user.id
            or existing.payload.get("fingerprint") != fingerprint
        ):
            raise HTTPException(409, "Request ID already used for a different operation")
        return existing
    data = deepcopy(payload.payload)
    mappings = []
    target = await mapping(session, op.entity, op.identifier) if op.identifier else None
    if target:
        if payload.expected_updated_at is None or utc(payload.expected_updated_at) != utc(
            datetime.fromisoformat(target.original["updated_at"])
        ):
            raise HTTPException(409, "Configuration changed; reopen the editor before saving")
        mappings.append(target)
    for container, key, entity in references(data):
        reference = await mapping(session, entity, container[key])
        mappings.append(reference)
        container[key] = reference.original["id"]
    edges = {m.edge_id for m in mappings}
    if payload.edge_id:
        edges.add(str(payload.edge_id))
    if not edges:
        edges = set(
            await session.scalars(select(EdgeInstallation.id).where(EdgeInstallation.enabled))
        )
    if len(edges) != 1:
        raise HTTPException(422, "Select one Edge; references cannot cross installations")
    edge = await session.get(EdgeInstallation, edges.pop())
    if edge is None or not edge.enabled:
        raise HTTPException(409, "Selected Edge is unavailable")
    if CAPABILITY not in edge.capabilities:
        raise HTTPException(409, "Update Edge to support remote configuration before editing")
    # Editors obtain original names/keys/default through context(). Never infer whether
    # a submitted field is intentional: especially false is a valid default change.
    versions = [
        {"entity": m.entity, "id": m.original["id"], "updated_at": m.original["updated_at"]}
        for m in {m.id: m for m in mappings}.values()
    ]
    now = datetime.now(UTC)
    row = RemoteRequest(
        id=str(payload.request_id),
        edge_id=edge.id,
        kind="configuration",
        target_id=target.original["id"] if target else 0,
        user_id=request.state.user.id,
        username=request.state.user.username,
        created_at=now,
        expires_at=now
        + timedelta(seconds=request.app.state.settings.remote_configuration_max_age_seconds),
        status="PENDING_EDGE",
        payload={
            "origin_user_id": request.state.user.id,
            "fingerprint": fingerprint,
            "path": op.path(target.original["id"] if target else None),
            "method": op.method,
            "values": data,
            "versions": versions,
        },
    )
    session.add(row)
    await session.commit()
    return row


async def context(session: AsyncSession, path: str) -> dict:
    op = operation(path, "GET")
    ref = await mapping(session, op.entity, op.identifier)
    record = await read(session, op.resource, op.identifier)
    fields = (
        {"key"}
        if op.resource == "tags"
        else {"name", "slug", "is_default"}
        if op.resource == "dashboards"
        else set()
    )
    for key in fields:
        record[key] = ref.original[key]
    return {"record": record, "edge_id": ref.edge_id, "updated_at": ref.original["updated_at"]}


async def status(session: AsyncSession, row: RemoteRequest) -> dict:
    result = {
        "id": row.id,
        "edge_id": row.edge_id,
        "path": row.payload["path"],
        "status": row.status,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "error": row.error,
        "data": None,
    }
    if row.status == "SUCCESS" and row.result and not row.result["deleted"]:
        resource, identifier = row.result["resource"], row.result["id"]
        op = operation(f"{resource}/{identifier}", "GET")
        key = json.dumps({"id": identifier}, separators=(",", ":"), sort_keys=True)
        ref = await session.get(SyncMapping, identity(row.edge_id, op.entity, key))
        if ref is None or not ref.cloud_id:
            result["status"] = "SYNCING"
        elif not ref.deleted:
            try:
                result["data"] = await read(session, resource, ref.cloud_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                result["error"] = "Saved on Edge; object was subsequently removed"
    return result
