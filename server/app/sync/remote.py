"""Remote delivery only enqueues existing commands; this module never accesses Modbus."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.models import (
    AlarmEvent,
    AuditLog,
    Command,
    Connection,
    Device,
    EdgeInstallation,
    RemoteInbox,
    RemoteRequest,
    SyncMapping,
    Tag,
    WorkerRuntime,
)
from app.schemas.telemetry import utc
from app.services.alarms import notify_event
from app.services.commands import enqueue_command, get_command, notify_command
from app.services.runtime import worker_alive
from app.sync.protocol import RemoteAction


async def cloud_mapping(session, entity: str, identifier: int):
    mapping = await session.scalar(
        select(SyncMapping).where(
            SyncMapping.entity == entity, SyncMapping.cloud_id == identifier, ~SyncMapping.deleted
        )
    )
    if mapping is None:
        raise HTTPException(409, "Edge mapping unavailable")
    edge = await session.get(EdgeInstallation, mapping.edge_id)
    if not edge.enabled:
        raise HTTPException(409, "Edge disabled")
    return edge, mapping


async def queue_command(session, request, payload, tag, device, connection):
    edge, mapping = await cloud_mapping(session, "tags", tag.id)
    runtime = edge.runtime
    if runtime.get("mode") not in ("simulator", "modbus"):
        raise HTTPException(409, "No confirmed Edge telemetry source")
    try:
        command = await enqueue_command(
            session,
            tag,
            device,
            connection,
            payload.value,
            mode=runtime["mode"],
            writes_enabled=runtime.get("writes_enabled", False),
            physical_confirmed=payload.confirm_physical,
            max_age_seconds=request.app.state.settings.remote_command_max_age_seconds,
            request_id=str(payload.request_id),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    command.status = "PENDING_EDGE"
    command.requested_by = request.state.user.id
    command.requested_by_username = request.state.user.username
    session.add(
        RemoteRequest(
            id=command.request_id,
            edge_id=edge.id,
            kind="command",
            target_id=mapping.original["id"],
            command_id=command.id,
            user_id=request.state.user.id,
            username=request.state.user.username,
            created_at=command.created_at,
            expires_at=command.expires_at,
            status="PENDING_EDGE",
            payload={
                "origin_user_id": request.state.user.id,
                "value": payload.value if isinstance(payload.value, bool) else str(payload.value),
                "mode": runtime["mode"],
                "confirm_physical": payload.confirm_physical,
                "versions": [utc(obj.updated_at).isoformat() for obj in (tag, device, connection)],
            },
        )
    )
    await session.commit()
    return await get_command(session, command.id)


async def queue_acknowledgement(session, request, alarm):
    edge, mapping = await cloud_mapping(session, "alarm_events", alarm.id)
    if alarm.state != "ACTIVE":
        raise HTTPException(409, "Only an ACTIVE alarm can be acknowledged")
    existing = await session.scalar(
        select(RemoteRequest).where(
            RemoteRequest.edge_id == edge.id,
            RemoteRequest.kind == "acknowledge",
            RemoteRequest.target_id == mapping.original["id"],
            RemoteRequest.status.in_(["PENDING_EDGE", "DELIVERED"]),
        )
    )
    if existing:
        return existing.id
    now = datetime.now(UTC)
    remote = RemoteRequest(
        id=str(uuid4()),
        edge_id=edge.id,
        kind="acknowledge",
        target_id=mapping.original["id"],
        user_id=request.state.user.id,
        username=request.state.user.username,
        payload={"origin_user_id": request.state.user.id},
        status="PENDING_EDGE",
        created_at=now,
        expires_at=now
        + timedelta(seconds=request.app.state.settings.remote_command_max_age_seconds),
    )
    session.add(remote)
    await session.commit()
    return remote.id


async def expire_remote(session):
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(RemoteRequest)
        .where(RemoteRequest.status == "PENDING_EDGE", RemoteRequest.expires_at <= now)
        .with_for_update(skip_locked=True)
        .limit(500)
    )
    for remote in rows:
        remote.status = "EXPIRED"
        remote.completed_at = now
        remote.error = "Expired before Edge delivery"
        if remote.command_id:
            command = await session.get(Command, remote.command_id)
            command.status = "EXPIRED"
            command.completed_at = now
            command.error_message = remote.error
            command.revision += 1
            await notify_command(session, command.id)


async def receive_result(session, edge, payload):
    if payload["status"] not in ("QUEUED", "SUCCESS", "FAILED", "EXPIRED"):
        raise ValueError("Invalid inbox result status")
    remote = await session.get(RemoteRequest, payload["id"])
    if remote is None or remote.edge_id != edge.id:
        raise ValueError("Unknown remote correlation")
    if remote.status in ("SUCCESS", "FAILED", "CANCELLED", "EXPIRED"):
        return
    remote.status = payload["status"]
    remote.error = payload["error"]
    if remote.status in ("SUCCESS", "FAILED", "EXPIRED"):
        remote.completed_at = datetime.now(UTC)
    if remote.command_id and remote.status in ("FAILED", "EXPIRED"):
        command = await session.get(Command, remote.command_id)
        command.status = remote.status
        command.error_message = remote.error
        command.completed_at = remote.completed_at
        command.revision += 1
        await notify_command(session, command.id)


async def accept_remote(session, settings, action: RemoteAction, installation_id: str):
    if str(action.edge_id) != installation_id:
        raise ValueError("Wrong Edge installation")
    # Caller owns a transaction and singleton sync lease; unique inbox + command request_id is durable.
    existing = await session.get(RemoteInbox, str(action.id))
    if existing:
        return existing
    now = datetime.now(UTC)
    inbox = RemoteInbox(
        id=str(action.id),
        kind=action.kind,
        cloud_user_id=action.user_id,
        cloud_username=action.username,
        received_at=now,
        status="FAILED",
    )
    try:
        if action.expires_at.tzinfo is None or utc(action.expires_at) <= now:
            inbox.status = "EXPIRED"
            inbox.error = "Remote request expired before local enqueue"
        elif action.kind == "acknowledge":
            if action.payload:
                raise ValueError("Unexpected acknowledgement payload")
            alarm = await session.scalar(
                select(AlarmEvent).where(AlarmEvent.id == action.target_id).with_for_update()
            )
            if alarm is None or alarm.state != "ACTIVE":
                raise ValueError("Alarm is no longer ACTIVE")
            alarm.state = "ACKNOWLEDGED"
            alarm.acknowledged_at = now
            alarm.acknowledged_by_username = ("Cloud: " + action.username)[:64]
            alarm.revision += 1
            await notify_event(session, alarm)
            inbox.status = "SUCCESS"
        else:
            if set(action.payload) != {"value", "mode", "confirm_physical", "versions"}:
                raise ValueError("Invalid remote command payload")
            row = (
                await session.execute(
                    select(Tag, Device, Connection)
                    .join(Device, Device.id == Tag.device_id)
                    .join(Connection, Connection.id == Device.connection_id)
                    .where(Tag.id == action.target_id)
                    .with_for_update(read=True, of=(Tag, Device, Connection))
                )
            ).first()
            if row is None:
                raise ValueError("Target Tag no longer exists")
            tag, device, connection = row
            if [utc(o.updated_at).isoformat() for o in row] != action.payload["versions"]:
                raise ValueError("Edge configuration changed after remote request")
            worker = await session.get(WorkerRuntime, 1)
            if not worker_alive(worker) or worker.mode != action.payload["mode"]:
                raise ValueError("Edge source changed or worker unavailable")
            value = action.payload["value"]
            if type(value) is not bool:
                value = Decimal(str(value))
            if type(action.payload["confirm_physical"]) is not bool:
                raise ValueError("Invalid physical confirmation")
            command = await enqueue_command(
                session,
                tag,
                device,
                connection,
                value,
                mode=worker.mode,
                writes_enabled=worker.writes_enabled,
                physical_confirmed=action.payload["confirm_physical"],
                max_age_seconds=settings.command_max_age_seconds,
                request_id=str(action.id),
            )
            command.expires_at = min(utc(command.expires_at), utc(action.expires_at))
            command.requested_by_username = ("Cloud: " + action.username)[:64]
            inbox.command_id = command.id
            inbox.status = "QUEUED"
        session.add(
            AuditLog(
                action="remote." + action.kind,
                entity_type="remote_inbox",
                summary=f"Cloud user {action.user_id} ({action.username}); request {action.id}; Edge {installation_id}; target {action.target_id}; result {inbox.status}",
                username=("Cloud: " + action.username)[:64],
            )
        )
    except (ValueError, ArithmeticError) as exc:
        inbox.status = "FAILED"
        inbox.error = str(exc)[:500]
        session.add(
            AuditLog(
                action="remote.rejected",
                entity_type="remote_inbox",
                summary=f"Remote request {action.id} rejected; Cloud user {action.user_id}",
                username=("Cloud: " + action.username)[:64],
            )
        )
    session.add(inbox)
    await session.flush()
    return inbox
