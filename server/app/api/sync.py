import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Command, EdgeInstallation, RemoteRequest, SyncMapping, SyncOutbox, SyncState
from app.schemas.telemetry import utc
from app.services.auth import digest
from app.services.commands import notify_command
from app.sync.mirror import DependencyPending, apply_event
from app.sync.protocol import Batch, Heartbeat
from app.sync.remote import expire_remote

machine_router = APIRouter(prefix="/api/sync/v1", tags=["machine sync"])
router = APIRouter(prefix="/api/sync", tags=["sync administration"])
Session = Annotated[AsyncSession, Depends(get_session)]


async def machine(request: Request, session: Session) -> EdgeInstallation:
    if request.app.state.settings.application_mode != "cloud":
        raise HTTPException(404, "Cloud sync is unavailable")
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    try:
        edge_id = str(UUID(request.headers.get("x-edge-id", "")))
    except ValueError:
        raise HTTPException(401, "Invalid Edge credentials") from None
    edge = await session.scalar(
        select(EdgeInstallation).where(EdgeInstallation.id == edge_id).with_for_update()
    )
    if (
        not token
        or len(token) > 256
        or not edge
        or not edge.enabled
        or not hmac.compare_digest(edge.token_hash, digest(token))
    ):
        raise HTTPException(401, "Invalid Edge credentials")
    return edge


Machine = Annotated[EdgeInstallation, Depends(machine)]


@machine_router.post("/heartbeat")
async def heartbeat(payload: Heartbeat, edge: Machine, session: Session):
    edge.last_seen_at = datetime.now(UTC)
    edge.software_version = payload.software_version
    await expire_remote(session)
    await session.commit()
    return {"version": 1, "edge_id": edge.id}


@machine_router.post("/events")
async def ingest(payload: Batch, edge: Machine, session: Session):
    if len(payload.model_dump_json()) > 4_000_000:
        raise HTTPException(413, "Batch too large")
    acknowledged = []
    deferred = []
    for event in payload.events:
        try:
            async with session.begin_nested():
                await apply_event(session, edge, event)
            acknowledged.append(str(event.event_id))
        except (DependencyPending, IntegrityError):
            deferred.append(
                {
                    "event_id": str(event.event_id),
                    "reason": "Referenced metadata or earlier lifecycle event pending",
                }
            )
        except (ValueError, TypeError, KeyError):
            deferred.append(
                {
                    "event_id": str(event.event_id),
                    "reason": "Invalid version 1 row; retained on Edge",
                }
            )
    edge.last_seen_at = datetime.now(UTC)
    await session.commit()
    return {"version": 1, "acknowledged": acknowledged, "deferred": deferred}


@machine_router.get("/requests")
async def requests(edge: Machine, session: Session):
    await expire_remote(session)
    rows = list(
        await session.scalars(
            select(RemoteRequest)
            .where(
                RemoteRequest.edge_id == edge.id,
                RemoteRequest.status.in_(["PENDING_EDGE", "DELIVERED"]),
            )
            .order_by(RemoteRequest.created_at)
            .limit(100)
        )
    )
    result = []
    for row in rows:
        # Delivered requests remain retryable until the durable Edge inbox/result acknowledges them.
        if row.status == "PENDING_EDGE":
            row.status = "DELIVERED"
            row.delivered_at = datetime.now(UTC)
            if row.command_id:
                cmd = await session.get(Command, row.command_id)
                cmd.status = "DELIVERED"
                cmd.revision += 1
                await notify_command(session, cmd.id)
        result.append(
            {
                "id": row.id,
                "edge_id": row.edge_id,
                "kind": row.kind,
                "target_id": row.target_id,
                "user_id": row.payload["origin_user_id"],
                "username": row.username,
                "expires_at": utc(row.expires_at).isoformat(),
                "payload": {k: v for k, v in row.payload.items() if k != "origin_user_id"},
            }
        )
    await session.commit()
    return {"version": 1, "requests": result}


class EdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str = Field(min_length=1, max_length=200)
    token: SecretStr = Field(min_length=32, max_length=256)
    enabled: bool = True


@router.post("/installations", status_code=201)
async def provision(payload: EdgeInput, request: Request, session: Session):
    if request.app.state.settings.application_mode != "cloud":
        raise HTTPException(409, "Provision installations on Cloud")
    row = await session.get(EdgeInstallation, str(payload.id))
    if row is None:
        row = EdgeInstallation(
            id=str(payload.id),
            name=payload.name,
            token_hash=digest(payload.token.get_secret_value()),
            enabled=payload.enabled,
        )
        session.add(row)
    else:
        row.name = payload.name
        row.token_hash = digest(payload.token.get_secret_value())
        row.enabled = payload.enabled
    await session.commit()
    return {"id": row.id, "name": row.name, "enabled": row.enabled}


@router.get("/status")
async def status(request: Request, session: Session):
    state = await session.get(SyncState, 1)
    edges = list(await session.scalars(select(EdgeInstallation).order_by(EdgeInstallation.name)))
    now = datetime.now(UTC)
    counts = dict(
        (
            await session.execute(
                select(SyncOutbox.entity, func.count()).group_by(SyncOutbox.entity)
            )
        ).all()
    )
    current = counts.get("tag_current_values", 0)
    history = counts.get("tag_history", 0)
    statuses = sum(counts.get(e, 0) for e in ("connection_runtime", "worker_runtime"))
    commands = sum(counts.get(e, 0) for e in ("commands", "remote_inbox"))
    events = sum(
        counts.get(e, 0)
        for e in (
            "alarm_events",
            "automation_runtime",
            "automation_executions",
            "automation_execution_commands",
        )
    )
    total = sum(counts.values())
    return {
        "pending_current": current,
        "pending_history": history,
        "pending_status": statuses,
        "pending_commands": commands,
        "pending_events": events,
        "pending_metadata": total - current - history - statuses - commands - events,
        "mode": request.app.state.settings.application_mode,
        "installation_id": state.installation_id if state else None,
        "pending": total,
        "last_sync_at": utc(state.last_sync_at).isoformat()
        if state and state.last_sync_at
        else None,
        "error": state.last_error if state else None,
        "edges": [
            {
                "id": e.id,
                "name": e.name,
                "enabled": e.enabled,
                "state": "DISABLED"
                if not e.enabled
                else "ONLINE"
                if e.last_seen_at and (now - utc(e.last_seen_at)).total_seconds() < 30
                else "OFFLINE",
                "last_seen_at": utc(e.last_seen_at).isoformat() if e.last_seen_at else None,
                "mode": e.runtime.get("mode", "unknown"),
            }
            for e in edges
        ],
    }


@router.get("/mappings")
async def mappings(session: Session, edge_id: UUID, entity: str = "tags"):
    if entity not in ("tags", "devices", "connections", "dashboards", "alarm_events"):
        raise HTTPException(422, "Unsupported metadata lookup")
    rows = await session.scalars(
        select(SyncMapping)
        .where(
            SyncMapping.edge_id == str(edge_id), SyncMapping.entity == entity, ~SyncMapping.deleted
        )
        .limit(1000)
    )
    return [
        {"public_id": r.id, "edge_id": r.edge_id, "id": r.cloud_id, "local_key": r.local_key}
        for r in rows
    ]


@router.get("/requests")
async def remote_requests(session: Session):
    await expire_remote(session)
    await session.commit()
    rows = await session.scalars(
        select(RemoteRequest).order_by(RemoteRequest.created_at.desc()).limit(100)
    )
    return [
        {
            "id": r.id,
            "edge_id": r.edge_id,
            "kind": r.kind,
            "command_id": r.command_id,
            "status": r.status,
            "username": r.username,
            "created_at": utc(r.created_at).isoformat(),
            "expires_at": utc(r.expires_at).isoformat(),
            "error": r.error,
        }
        for r in rows
    ]
