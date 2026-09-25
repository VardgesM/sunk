from typing import TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models import (
    Connection,
    ConnectionRuntime,
    Device,
    Location,
    Tag,
    TagCurrentValue,
    TagHistory,
)
from app.services.current_values import notify_current

Model = TypeVar("Model", bound=Base)
Schema = TypeVar("Schema", bound=BaseModel)


async def get_record(
    session: AsyncSession, model: type[Model], identifier: int, *, lock: bool = False
) -> Model:
    statement = select(model).where(model.id == identifier)
    if lock:
        statement = statement.with_for_update()
    record = await session.scalar(statement)
    if record is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return record


def merge_patch(record: Base, patch: BaseModel, schema: type[Schema]) -> Schema:
    values = {name: getattr(record, name) for name in schema.model_fields}
    values.update(patch.model_dump(exclude_unset=True))
    try:
        return schema.model_validate(values)
    except ValidationError as exc:
        errors = exc.errors(include_context=False)
        for error in errors:
            error["loc"] = ("body", *error["loc"])
        raise RequestValidationError(errors) from exc


async def lock_locations(session: AsyncSession) -> None:
    # Serialize infrequent hierarchy mutations, preventing concurrent A->B / B->A edits.
    # Acquire before reading the tree or locking an individual location row.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("LOCK TABLE locations IN SHARE ROW EXCLUSIVE MODE"))


async def validate_parent(
    session: AsyncSession, parent_id: int | None, identifier: int | None = None
) -> None:
    seen = {identifier} if identifier is not None else set()
    while parent_id is not None:
        if parent_id in seen:
            raise HTTPException(422, "A location cannot be its own ancestor")
        seen.add(parent_id)
        parent = await session.get(Location, parent_id)
        if parent is None:
            raise HTTPException(422, "parent_id references a location that does not exist")
        parent_id = parent.parent_id


async def require_reference(
    session: AsyncSession, model: type[Base], identifier: int | None, field: str
) -> None:
    if identifier is not None and await session.get(model, identifier) is None:
        raise HTTPException(
            422, f"{field} references a {model.__name__.lower()} that does not exist"
        )


async def persist(session: AsyncSession, record: Model) -> Model:
    session.add(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        code = getattr(exc.orig, "sqlstate", None)
        # SQLite constraint names are used only by isolated tests; PostgreSQL uses SQLSTATE.
        message = str(exc.orig)
        if code == "23505" or "UNIQUE constraint failed" in message:
            detail = (
                "Tag key already exists"
                if isinstance(record, Tag)
                else "A device with this connection and slave ID already exists"
            )
            raise HTTPException(409, detail) from exc
        if code == "23503" or "FOREIGN KEY constraint failed" in message:
            raise HTTPException(422, "Referenced configuration no longer exists") from exc
        if code in ("23514", "23502") or "CHECK constraint failed" in message:
            raise HTTPException(422, "Configuration violates a database constraint") from exc
        raise
    await session.refresh(record)
    return record


async def remove(session: AsyncSession, record: Base) -> None:
    if isinstance(record, Connection):
        await session.execute(
            delete(ConnectionRuntime).where(ConnectionRuntime.connection_id == record.id)
        )
    if isinstance(record, Tag):
        if await session.scalar(
            select(TagHistory.id).where(TagHistory.tag_id == record.id).limit(1)
        ):
            raise HTTPException(
                409,
                "Cannot delete: retained history exists; disable the tag and configure retention",
            )
        # Derived latest state is explicitly removed with its tag, never configuration children.
        await session.execute(delete(TagCurrentValue).where(TagCurrentValue.tag_id == record.id))
        await notify_current(session, record.id)
    await session.delete(record)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if getattr(exc.orig, "sqlstate", None) == "23503" or "FOREIGN KEY constraint failed" in str(
            exc.orig
        ):
            raise HTTPException(409, "Cannot delete: dependent configuration exists") from exc
        raise


def apply_values(record: Base, schema: BaseModel) -> None:
    for name, value in schema.model_dump().items():
        setattr(record, name, value)


async def validate_device_references(
    session: AsyncSession, connection_id: int, location_id: int | None
) -> None:
    await require_reference(session, Connection, connection_id, "connection_id")
    await require_reference(session, Location, location_id, "location_id")


async def validate_tag_reference(session: AsyncSession, device_id: int) -> None:
    await require_reference(session, Device, device_id, "device_id")
