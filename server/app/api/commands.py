from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Command, Connection, Device, Tag, TagCurrentValue, WorkerRuntime
from app.schemas.commands import CommandCreate, CommandRead, CommandStatus
from app.services.commands import (
    command_query,
    command_value,
    get_command,
    notify_command,
    serialize_command,
    validate_write,
)
from app.services.runtime import worker_alive

router = APIRouter(prefix="/api", tags=["commands"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


@router.post("/tags/{tag_id}/commands", response_model=CommandRead, status_code=202)
async def request_command(
    tag_id: Identifier, payload: CommandCreate, request: Request, session: Session
) -> CommandRead:
    existing = await session.scalar(
        select(Command).where(Command.request_id == str(payload.request_id))
    )
    if existing:
        if (
            existing.tag_id != tag_id
            or command_value(existing, "requested") != payload.value
            or type(command_value(existing, "requested")) is not type(payload.value)
        ):
            raise HTTPException(409, "Request ID already used for another command")
        return await get_command(session, existing.id)
    row = (
        await session.execute(
            select(Tag, Device, Connection)
            .join(Device, Device.id == Tag.device_id)
            .join(Connection, Connection.id == Device.connection_id)
            .where(Tag.id == tag_id)
            .with_for_update(read=True, of=(Tag, Device, Connection))
        )
    ).first()
    if not row:
        raise HTTPException(404, "Tag not found")
    tag, device, connection = row
    try:
        validate_write(tag, device, connection, payload.value)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    worker = await session.get(WorkerRuntime, 1)
    if not worker_alive(worker) or worker.mode not in ("simulator", "modbus"):
        raise HTTPException(503, "An active telemetry worker is required")
    if worker.mode == "modbus":
        if not worker.writes_enabled:
            raise HTTPException(409, "Physical writes are disabled on the worker")
        if not payload.confirm_physical:
            raise HTTPException(422, "Explicit physical-write confirmation is required")
    now = datetime.now(UTC)
    current = await session.get(TagCurrentValue, tag_id)
    boolean = type(payload.value) is bool
    command = Command(
        request_id=str(payload.request_id),
        tag_id=tag_id,
        requested_boolean=payload.value if boolean else None,
        requested_numeric=None if boolean else payload.value,
        previous_numeric=current.value_numeric if current else None,
        previous_boolean=current.value_boolean if current else None,
        status="QUEUED",
        source="manual",
        telemetry_mode=worker.mode,
        physical_confirmed=payload.confirm_physical,
        created_at=now,
        expires_at=now + timedelta(seconds=request.app.state.settings.command_max_age_seconds),
        tag_version=tag.updated_at,
        device_version=device.updated_at,
        connection_version=connection.updated_at,
    )
    session.add(command)
    try:
        await session.flush()
        await notify_command(session, command.id)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Command request already exists; retrieve by request_id") from exc
    return await get_command(session, command.id)


@router.get("/commands", response_model=list[CommandRead])
async def list_commands(
    session: Session,
    status: CommandStatus | None = None,
    tag_id: int | None = Query(None, gt=0, le=2147483647),
    device_id: int | None = Query(None, gt=0, le=2147483647),
    request_id: str | None = Query(None, max_length=36),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[CommandRead]:
    statement = command_query()
    for column, value in (
        (Command.status, status),
        (Command.tag_id, tag_id),
        (Device.id, device_id),
        (Command.request_id, request_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    rows = (
        await session.execute(statement.order_by(Command.id.desc()).limit(limit).offset(offset))
    ).all()
    return [serialize_command(*row) for row in rows]


@router.get("/commands/{identifier}", response_model=CommandRead)
async def read_command(identifier: Identifier, session: Session) -> CommandRead:
    command = await get_command(session, identifier)
    if command is None:
        raise HTTPException(404, "Command not found")
    return command


@router.post("/commands/{identifier}/cancel", response_model=CommandRead)
async def cancel_command(identifier: Identifier, session: Session) -> CommandRead:
    command = await session.scalar(
        select(Command).where(Command.id == identifier).with_for_update()
    )
    if command is None:
        raise HTTPException(404, "Command not found")
    if command.status != "QUEUED":
        raise HTTPException(
            409, "Only QUEUED commands can be cancelled; a physical action cannot be undone"
        )
    command.status, command.completed_at = "CANCELLED", datetime.now(UTC)
    command.revision += 1
    await notify_command(session, command.id)
    await session.commit()
    return await get_command(session, identifier)
