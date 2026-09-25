import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.models import Tag, TagHistory

logger = logging.getLogger(__name__)


async def cleanup_batch(
    session: AsyncSession, tag_id: int, cutoff: datetime, batch_size: int = 5000
) -> int:
    identifiers = (
        select(TagHistory.id)
        .where(TagHistory.tag_id == tag_id, TagHistory.recorded_at < cutoff)
        .order_by(TagHistory.recorded_at, TagHistory.id)
        .limit(batch_size)
    )
    result = await session.execute(delete(TagHistory).where(TagHistory.id.in_(identifiers)))
    return result.rowcount


async def retention_loop(database: Database, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            # Keyset pages keep configuration scans bounded as the inventory grows.
            after = 0
            total = 0
            while not stop.is_set():
                async with database.sessions() as session:
                    policies = (
                        await session.execute(
                            select(Tag.id, Tag.history_retention_days)
                            .where(Tag.id > after, Tag.history_retention_days.is_not(None))
                            .order_by(Tag.id)
                            .limit(100)
                        )
                    ).all()
                if not policies:
                    break
                for tag_id, days in policies:
                    after = tag_id
                    cutoff = datetime.now(UTC) - timedelta(days=days)
                    # Bound each tag's work per maintenance pass to avoid starving collection.
                    for _ in range(20):
                        if stop.is_set():
                            break
                        async with database.sessions() as session, session.begin():
                            removed = await cleanup_batch(session, tag_id, cutoff)
                        total += removed
                        if removed < 5000:
                            break
                        await asyncio.sleep(0)
            if total:
                logger.info("History retention removed %s expired rows", total)
        except Exception:
            logger.exception("History retention failed; retrying next maintenance interval")
        try:
            await asyncio.wait_for(stop.wait(), settings.history_cleanup_seconds)
        except TimeoutError:
            continue
