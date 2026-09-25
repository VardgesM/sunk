import asyncio
import logging
from typing import Annotated

from asyncpg import PostgresError
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.health import DatabaseHealthResponse, HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/db", response_model=DatabaseHealthResponse)
async def database_health(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatabaseHealthResponse:
    try:
        async with asyncio.timeout(6):
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    return DatabaseHealthResponse()
