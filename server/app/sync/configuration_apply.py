"""Apply one authenticated, version-checked configuration request on its owning Edge."""

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import AuditLog, RemoteInbox
from app.schemas.telemetry import utc
from app.services.configuration_lock import lock_configuration_lifecycle
from app.sync.configuration_dispatch import RESOURCES, execute, operation
from app.sync.configuration_queue import references
from app.sync.protocol import RemoteAction

logger = logging.getLogger(__name__)


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity: str
    id: int = Field(gt=0)
    updated_at: datetime


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    path: str = Field(max_length=120)
    method: Literal["POST", "PATCH", "DELETE"]
    values: dict
    versions: list[Version] = Field(max_length=1000)


async def apply_configuration(
    session: AsyncSession, settings: Settings, action: RemoteAction, installation_id: str
) -> RemoteInbox:
    if settings.application_mode != "edge" or str(action.edge_id) != installation_id:
        raise ValueError("Remote configuration requires its owning Edge")
    # Exclusive before row locks: archive and ordinary mutations share one ordering.
    await lock_configuration_lifecycle(session, exclusive=True)
    existing = await session.get(RemoteInbox, str(action.id))
    if existing:
        return existing
    now = datetime.now(UTC)
    state, error, result = "FAILED", None, None
    try:
        if not settings.remote_configuration_enabled:
            raise HTTPException(409, "Remote configuration disabled on Edge")
        if action.expires_at.tzinfo is None or utc(action.expires_at) <= now:
            state, error = "EXPIRED", "Configuration request expired before Edge application"
        else:
            change = Change.model_validate(action.payload)
            if len(change.model_dump_json()) > 200_000:
                raise HTTPException(413, "Configuration request too large")
            op = operation(change.path, change.method)
            if (op.identifier or 0) != action.target_id:
                raise HTTPException(422, "Configuration target mismatch")
            required = {
                (entity, container[key]) for container, key, entity in references(change.values)
            }
            if op.identifier:
                required.add((op.entity, op.identifier))
            if required != {(v.entity, v.id) for v in change.versions} or len(
                change.versions
            ) != len(required):
                raise HTTPException(422, "Missing configuration version guards")
            models = {entry[0].__tablename__: entry[0] for entry in RESOURCES.values()}
            for version in change.versions:
                model = models.get(version.entity)
                row = (
                    await session.get(model, version.id, populate_existing=True) if model else None
                )
                if row is None or getattr(row, "archived_at", None) is not None:
                    raise HTTPException(409, "Referenced configuration was removed on Edge")
                if version.updated_at.tzinfo is None or utc(row.updated_at) != utc(
                    version.updated_at
                ):
                    raise HTTPException(409, "Configuration changed on Edge; reopen the editor")
            session.info["remote_configuration"] = True
            try:
                async with session.begin_nested():
                    saved = await execute(session, op, change.values)
                    await session.flush()
                    result = {
                        "resource": "dashboard-widgets" if op.child == "widgets" else op.resource,
                        "id": op.identifier if op.method == "DELETE" else saved.id,
                        "deleted": op.method == "DELETE",
                    }
                state = "SUCCESS"
            finally:
                session.info.pop("remote_configuration", None)
    except (ValidationError, RequestValidationError):
        error = "Invalid configuration; check the field values and Tag compatibility"
    except IntegrityError:
        error = "Configuration conflicts with existing identifiers or references"
    except DBAPIError:
        # Connectivity/serialization failures are not a durable business rejection.
        # Abort the outer transaction; the same request is safely redelivered later.
        raise
    except HTTPException as exc:
        # Existing validation may embed submitted values; never echo it as a remote error.
        error = (
            str(exc.detail)[:500]
            if exc.status_code in (404, 409)
            else "Invalid configuration; check fields and references"
        )
    except Exception as exc:
        logger.error("Remote configuration failed (%s); request %s", type(exc).__name__, action.id)
        error = "Edge could not apply configuration; inspect Edge health and retry explicitly"
    inbox = RemoteInbox(
        id=str(action.id),
        kind="configuration",
        cloud_user_id=action.user_id,
        cloud_username=action.username,
        received_at=now,
        status=state,
        error=error,
        result=result,
    )
    # Handler changes and this idempotency receipt commit together. Result is flushed LAST.
    session.add(
        AuditLog(
            action="remote.configuration",
            entity_type="remote_inbox",
            username=("Cloud: " + action.username)[:64],
            summary=f"Cloud user {action.user_id}; request {action.id}; Edge {installation_id}; result {state}",
        )
    )
    session.add(inbox)
    await session.flush()
    return inbox
