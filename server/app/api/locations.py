from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Location
from app.schemas.configuration import LocationCreate, LocationPatch, LocationRead
from app.services.configuration import (
    apply_values,
    get_record,
    lock_locations,
    merge_patch,
    persist,
    remove,
    validate_parent,
)

router = APIRouter(prefix="/api/locations", tags=["locations"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[LocationRead])
async def list_locations(
    session: Session,
    parent_id: int | None = Query(None, gt=0, le=2147483647),
    roots_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=2147483647),
) -> list[Location]:
    statement = select(Location)
    if parent_id is not None:
        statement = statement.where(Location.parent_id == parent_id)
    if roots_only:
        statement = statement.where(Location.parent_id.is_(None))
    result = await session.scalars(
        statement.order_by(Location.sort_order, Location.name, Location.id)
        .limit(limit)
        .offset(offset)
    )
    return list(result.all())


@router.post("", response_model=LocationRead, status_code=201)
async def create_location(data: LocationCreate, session: Session) -> Location:
    await lock_locations(session)
    await validate_parent(session, data.parent_id)
    return await persist(session, Location(**data.model_dump()))


@router.get("/{identifier}", response_model=LocationRead)
async def read_location(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Location:
    return await get_record(session, Location, identifier)


@router.patch("/{identifier}", response_model=LocationRead)
async def update_location(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], patch: LocationPatch, session: Session
) -> Location:
    await lock_locations(session)
    record = await get_record(session, Location, identifier, lock=True)
    data = merge_patch(record, patch, LocationCreate)
    await validate_parent(session, data.parent_id, identifier)
    apply_values(record, data)
    return await persist(session, record)


@router.delete("/{identifier}", status_code=204)
async def delete_location(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Response:
    await lock_locations(session)
    await remove(session, await get_record(session, Location, identifier, lock=True))
    return Response(status_code=204)
