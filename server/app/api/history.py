from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import Tag
from app.schemas.history import HistoryResponse
from app.services.configuration import get_record
from app.services.history_query import query_history

router = APIRouter(prefix="/api/tags", tags=["history"])


@router.get("/{identifier}/history", response_model=HistoryResponse)
async def history(
    identifier: Annotated[int, Path(ge=1, le=2147483647)],
    session: Annotated[AsyncSession, Depends(get_session)],
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int = Query(1000, ge=1, le=5000),
    order: Literal["asc", "desc"] = "asc",
    max_points: int | None = Query(None, ge=1, le=2000),
) -> HistoryResponse:
    end = end or datetime.now(UTC)
    start = start or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(422, "from/to must include a UTC offset")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start >= end or end - start > timedelta(days=366):
        raise HTTPException(422, "History range must be positive and no longer than 366 days")
    tag = await get_record(session, Tag, identifier)
    return await query_history(session, tag, start, end, limit, order, max_points)
