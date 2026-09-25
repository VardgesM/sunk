from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Connection, Device, Tag, TagCurrentValue
from app.schemas.telemetry import CurrentValueRead, Quality
from app.services.current_values import current_statement, get_current, serialize_current

router = APIRouter(prefix="/api/tags", tags=["current values"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/values", response_model=list[CurrentValueRead])
async def current_values(
    session: Session,
    tag_id: int | None = Query(None, ge=1, le=2147483647),
    device_id: int | None = Query(None, ge=1, le=2147483647),
    enabled: bool | None = None,
    quality: Quality | None = None,
    after_tag_id: int = Query(0, ge=0, le=2147483647),
    limit: int = Query(100, ge=1, le=500),
) -> list[CurrentValueRead]:
    statement = current_statement().where(Tag.id > after_tag_id)
    if tag_id is not None:
        statement = statement.where(Tag.id == tag_id)
    if device_id is not None:
        statement = statement.where(Tag.device_id == device_id)
    if enabled is not None:
        statement = statement.where((Tag.enabled & Device.enabled & Connection.enabled) == enabled)
    if quality is not None:
        statement = statement.where(TagCurrentValue.quality == quality)
    rows = await session.execute(statement.order_by(Tag.id).limit(limit))
    return [serialize_current(*row) for row in rows]


@router.get("/{identifier}/value", response_model=CurrentValueRead)
async def tag_value(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> CurrentValueRead:
    value = await get_current(session, identifier)
    if value is None:
        raise HTTPException(404, "Tag not found")
    return value
