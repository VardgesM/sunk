from typing import TypeVar

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.models import (
    Connection,
    Device,
    Location,
    Tag,
)
from app.services.configuration_lock import lock_configuration_lifecycle

Model = TypeVar("Model", bound=Base)
Schema = TypeVar("Schema", bound=BaseModel)


async def get_record(
    session: AsyncSession, model: type[Model], identifier: int, *, lock: bool = False, include_archived: bool = False
) -> Model:
    if lock:
        await lock_configuration_lifecycle(session)
    statement = select(model).where(model.id == identifier)
    if not include_archived:
        statement = statement.where(model.archived_at.is_(None))
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
    await lock_configuration_lifecycle(session)
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
        if parent is None or parent.archived_at is not None:
            raise HTTPException(422, "parent_id references a location that does not exist")
        parent_id = parent.parent_id


async def require_reference(
    session: AsyncSession, model: type[Base], identifier: int | None, field: str
) -> None:
    await lock_configuration_lifecycle(session)
    record = await session.get(model, identifier) if identifier is not None else None
    if identifier is not None and (record is None or record.archived_at is not None):
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


async def remove(session: AsyncSession, model: type[Model], identifier: int) -> None:
    from app.services.archive import archive_configuration

    await archive_configuration(session, model, identifier)
    await session.commit()


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
