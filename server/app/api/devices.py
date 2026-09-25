from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Device
from app.schemas.configuration import DeviceCreate, DevicePatch, DeviceRead
from app.services.configuration import (
    apply_values,
    get_record,
    merge_patch,
    persist,
    remove,
    validate_device_references,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    session: Session,
    connection_id: int | None = Query(None, gt=0, le=2147483647),
    location_id: int | None = Query(None, gt=0, le=2147483647),
    enabled: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=2147483647),
) -> list[Device]:
    statement = select(Device)
    if connection_id is not None:
        statement = statement.where(Device.connection_id == connection_id)
    if location_id is not None:
        statement = statement.where(Device.location_id == location_id)
    if enabled is not None:
        statement = statement.where(Device.enabled == enabled)
    result = await session.scalars(
        statement.order_by(Device.name, Device.id).limit(limit).offset(offset)
    )
    return list(result.all())


@router.post("", response_model=DeviceRead, status_code=201)
async def create_device(data: DeviceCreate, session: Session) -> Device:
    await validate_device_references(session, data.connection_id, data.location_id)
    return await persist(session, Device(**data.model_dump()))


@router.get("/{identifier}", response_model=DeviceRead)
async def read_device(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Device:
    return await get_record(session, Device, identifier)


@router.patch("/{identifier}", response_model=DeviceRead)
async def update_device(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], patch: DevicePatch, session: Session
) -> Device:
    record = await get_record(session, Device, identifier, lock=True)
    data = merge_patch(record, patch, DeviceCreate)
    await validate_device_references(session, data.connection_id, data.location_id)
    apply_values(record, data)
    return await persist(session, record)


@router.delete("/{identifier}", status_code=204)
async def delete_device(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Response:
    await remove(session, await get_record(session, Device, identifier, lock=True))
    return Response(status_code=204)
