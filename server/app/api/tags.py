from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Tag, TagCurrentValue
from app.schemas.configuration import RegisterType, TagCreate, TagPatch, TagRead
from app.services.configuration import (
    apply_values,
    get_record,
    merge_patch,
    persist,
    remove,
    validate_tag_reference,
)
from app.services.current_values import notify_current, upsert_current

router = APIRouter(prefix="/api/tags", tags=["tags"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[TagRead])
async def list_tags(
    session: Session,
    device_id: int | None = Query(None, gt=0, le=2147483647),
    register_type: RegisterType | None = None,
    enabled: bool | None = None,
    search: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0, le=2147483647),
) -> list[Tag]:
    statement = select(Tag)
    if device_id is not None:
        statement = statement.where(Tag.device_id == device_id)
    if register_type is not None:
        statement = statement.where(Tag.register_type == register_type)
    if enabled is not None:
        statement = statement.where(Tag.enabled == enabled)
    if search:
        statement = statement.where(
            or_(
                Tag.name.icontains(search, autoescape=True),
                Tag.key.icontains(search, autoescape=True),
            )
        )
    result = await session.scalars(statement.order_by(Tag.name, Tag.id).limit(limit).offset(offset))
    return list(result.all())


@router.post("", response_model=TagRead, status_code=201)
async def create_tag(data: TagCreate, session: Session) -> Tag:
    await validate_tag_reference(session, data.device_id)
    return await persist(session, Tag(**data.model_dump()))


@router.get("/{identifier}", response_model=TagRead)
async def read_tag(identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session) -> Tag:
    return await get_record(session, Tag, identifier)


@router.patch("/{identifier}", response_model=TagRead)
async def update_tag(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], patch: TagPatch, session: Session
) -> Tag:
    record = await get_record(session, Tag, identifier, lock=True)
    data = merge_patch(record, patch, TagCreate)
    await validate_tag_reference(session, data.device_id)
    encoding_fields = (
        "device_id",
        "register_type",
        "address",
        "data_type",
        "byte_order",
        "word_order",
        "scale",
        "offset",
        "min_value",
        "max_value",
    )
    invalidate = any(getattr(record, field) != getattr(data, field) for field in encoding_fields)
    current = await session.get(TagCurrentValue, identifier)
    if current is not None:
        if invalidate:
            await upsert_current(
                session,
                identifier,
                quality="BAD" if data.enabled else "DISABLED",
                error="Configuration changed; awaiting a fresh reading",
                clear_value=True,
                history_policy=data,
            )
        elif not data.enabled:
            await upsert_current(session, identifier, quality="DISABLED", history_policy=data)
        else:
            await notify_current(session, identifier)
    apply_values(record, data)
    return await persist(session, record)


@router.delete("/{identifier}", status_code=204)
async def delete_tag(
    identifier: Annotated[int, Path(ge=1, le=2147483647)], session: Session
) -> Response:
    await remove(session, await get_record(session, Tag, identifier, lock=True))
    return Response(status_code=204)
