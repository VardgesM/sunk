"""CRUD may participate in the caller's atomic remote-inbox transaction."""

from sqlalchemy.ext.asyncio import AsyncSession


async def commit_configuration(session: AsyncSession) -> None:
    if session.info.get("remote_configuration"):
        await session.flush()
    else:
        await session.commit()


async def rollback_configuration(session: AsyncSession) -> None:
    if not session.info.get("remote_configuration"):
        await session.rollback()
