"""A point-in-time database recovery must not silently replay distributed state."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RecoveryState


async def sync_blocked(session: AsyncSession) -> bool:
    state = await session.get(RecoveryState, 1)
    return bool(state and state.sync_review_required)
