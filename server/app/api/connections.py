from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Connection
from app.schemas.configuration import ConnectionCreate, ConnectionPatch, ConnectionRead, Protocol
from app.services.configuration import (
    apply_values,
    get_record,
    merge_patch,
    persist,
    remove,
)

router = APIRouter(prefix="/api/connections", tags=["connections"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[ConnectionRead])
async def list_connections(
    session: Session,
    protocol: Protocol | None = None,
    enabled: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=2147483647),
) -> list[Connection]:
    statement = select(Connection)
    if protocol is not None:
        statement = statement.where(Connection.protocol == protocol)
    if enabled is not None:
        statement = statement.where(Connection.enabled == enabled)
    result = await session.scalars(
        statement.order_by(Connection.name, Connection.id).limit(limit).offset(offset)
    )
    return list(result.all())


@router.post("", response_model=ConnectionRead, status_code=201)
async def create_connection(data: ConnectionCreate, session: Session) -> Connection:
    return await persist(session, Connection(**data.model_dump()))


@router.get("/{identifier}", response_model=ConnectionRead)
async def read_connection(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Connection:
    return await get_record(session, Connection, identifier)


@router.patch("/{identifier}", response_model=ConnectionRead)
async def update_connection(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], patch: ConnectionPatch, session: Session
) -> Connection:
    record = await get_record(session, Connection, identifier, lock=True)
    data = merge_patch(record, patch, ConnectionCreate)

    apply_values(record, data)
    return await persist(session, record)


@router.delete("/{identifier}", status_code=204)
async def delete_connection(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Response:
    await remove(session, await get_record(session, Connection, identifier, lock=True))
    return Response(status_code=204)
