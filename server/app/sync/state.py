from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database
from app.models import SyncState
from app.sync.catalog import PRIORITIES


async def initialize(database: Database, settings: Settings) -> None:
    if settings.application_mode == "standalone":
        return
    async with database.sessions() as session, session.begin():
        await session.execute(text("SELECT pg_advisory_xact_lock(927011)"))
        state = await session.get(SyncState, 1)
        identity = (
            str(UUID(settings.edge_installation_id)) if settings.edge_installation_id else None
        )
        if state:
            if (
                state.mode != settings.application_mode
                or identity
                and state.installation_id != identity
            ):
                raise RuntimeError(
                    "Database mode/installation identity cannot be changed implicitly"
                )
            return
        if settings.application_mode == "edge":
            # Bootstrap atomically with capture activation. Stream rows in SQL, never load history in RAM.
            await session.execute(
                text("LOCK TABLE " + ",".join(PRIORITIES) + " IN SHARE ROW EXCLUSIVE MODE")
            )
        state = SyncState(
            id=1,
            mode=settings.application_mode,
            installation_id=identity or str(uuid4()),
            initialized=True,
        )
        session.add(state)
        await session.flush()
        if state.mode == "edge":
            for entity, priority in PRIORITIES.items():
                await session.execute(
                    text(
                        f"""
                        INSERT INTO sync_outbox
                          (event_id,entity,operation,priority,payload,created_at,coalesce_key)
                        SELECT gen_random_uuid()::text, CAST(:entity AS text), 'upsert',
                          :priority, sync_document(:entity,to_jsonb(t)), now(),
                          sync_state_key(:entity,to_jsonb(t)) FROM {entity} t
                        ON CONFLICT (coalesce_key) DO UPDATE SET
                          id=EXCLUDED.id,event_id=EXCLUDED.event_id,operation=EXCLUDED.operation,
                          payload=EXCLUDED.payload,created_at=EXCLUDED.created_at,retry_at=NULL
                        """
                    ),
                    {"entity": entity, "priority": priority},
                )
