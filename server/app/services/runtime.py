from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkerRuntime
from app.schemas.telemetry import utc


async def upsert_runtime(session: AsyncSession, model: Any, key: str, values: dict) -> None:
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(model).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[key],
            set_={name: value for name, value in values.items() if name != key},
        )
    )


def worker_alive(worker: WorkerRuntime | None) -> bool:
    return (
        worker is not None and (datetime.now(UTC) - utc(worker.heartbeat_at)).total_seconds() < 15
    )
