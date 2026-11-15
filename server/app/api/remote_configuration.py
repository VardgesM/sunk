from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import RemoteRequest
from app.sync.configuration_queue import ConfigurationRequest, context, enqueue, status
from app.sync.remote import expire_remote

router = APIRouter(prefix="/api/sync/configuration", tags=["remote configuration"])
Session = Annotated[AsyncSession, Depends(get_session)]


def cloud(request: Request) -> None:
    if request.app.state.settings.application_mode != "cloud":
        raise HTTPException(409, "Use local configuration APIs on Edge")


@router.get("/context")
async def edit_context(request: Request, session: Session, path: str = Query(max_length=120)):
    cloud(request)
    return await context(session, path)


@router.post("/requests", status_code=202)
async def create(payload: ConfigurationRequest, request: Request, session: Session):
    cloud(request)
    return await status(session, await enqueue(session, request, payload))


@router.get("/requests")
async def recent(request: Request, session: Session):
    cloud(request)
    await expire_remote(session)
    await session.commit()
    rows = await session.scalars(
        select(RemoteRequest)
        .where(RemoteRequest.kind == "configuration")
        .order_by(RemoteRequest.created_at.desc())
        .limit(50)
    )
    return [await status(session, row) for row in rows]


@router.get("/requests/{identifier}")
async def read_request(identifier: UUID, request: Request, session: Session):
    cloud(request)
    await expire_remote(session)
    await session.commit()
    row = await session.get(RemoteRequest, str(identifier))
    if row is None or row.kind != "configuration":
        raise HTTPException(404, "Configuration request not found")
    return await status(session, row)
