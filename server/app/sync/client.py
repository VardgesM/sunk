"""Independent HTTPS store-and-forward. No device access; no interactive user session."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import Select, case, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import Database
from app.models import SyncOutbox, SyncState
from app.sync.catalog import CURRENT_ENTITIES, STATUS_ENTITIES
from app.sync.protocol import RemoteAction
from app.sync.remote import accept_remote

logger = logging.getLogger(__name__)


class SyncClient:
    def __init__(
        self, database: Database, settings: Settings, http: httpx.AsyncClient | None = None
    ) -> None:
        self.database, self.settings = database, settings
        url = urlsplit(settings.sync_cloud_url)
        if (
            url.scheme not in ("http", "https")
            or not url.netloc
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Use a plain Cloud HTTPS base URL without credentials/query")
        if url.scheme != "https" and not settings.sync_allow_insecure_http:
            raise ValueError("Cloud synchronization requires HTTPS")
        if len(settings.sync_token.get_secret_value()) < 32:
            raise ValueError("A machine token of at least 32 characters is required")
        self.http = http or httpx.AsyncClient(
            base_url=settings.sync_cloud_url.rstrip("/") + "/",
            timeout=settings.sync_timeout_seconds,
            follow_redirects=False,
        )
        self.failures = 0
        # Scheduling hint only; pending data and ordering remain durable in PostgreSQL.
        self.current_cursor: str | None = None

    async def cycle(self) -> None:
        from app.services.recovery import sync_blocked

        async with self.database.sessions() as session:
            if await sync_blocked(session):
                raise ValueError("Synchronization paused after database restore; reconciliation required")
            state = await session.get(SyncState, 1)
            if not state or state.mode != "edge":
                raise ValueError("Sync requires initialized Edge database")
            identity = state.installation_id
        headers = {
            "Authorization": "Bearer " + self.settings.sync_token.get_secret_value(),
            "X-Edge-ID": identity,
        }

        async def call(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            response = await self.http.request(
                method, "api/sync/v1/" + path, headers=headers, **kwargs
            )
            response.raise_for_status()
            data = response.json()
            if data.get("version") != 1:
                raise ValueError("Unsupported Cloud protocol")
            return data

        await call("POST", "heartbeat", json={"version": 1, "software_version": "0.1.0"})
        requests = await call("GET", "requests")
        for data in requests["requests"]:
            action = RemoteAction.model_validate(data)
            async with self.database.sessions() as session, session.begin():
                await accept_remote(session, self.settings, action, identity)
        # Small bounded dependency/event batch first; never share a FIFO lane with history.
        async with self.database.sessions() as session:
            events = []
            per_lane = max(1, self.settings.sync_batch_size // 4)
            for priority in (0, 1, 2, 4):
                rows = await session.scalars(
                    self.ready()
                    .where(SyncOutbox.priority == priority)
                    .order_by(SyncOutbox.id)
                    .limit(per_lane)
                )
                events.extend(self.serialize(row) for row in rows)
        deferred = await self.send(call, events)
        # Read latest payloads immediately before each upload, not at the start of a long cycle.
        for entities, limit in (
            (
                CURRENT_ENTITIES,
                self.settings.sync_current_batch_size or self.settings.sync_batch_size,
            ),
            (STATUS_ENTITIES, self.settings.sync_batch_size),
            (
                ("tag_history",),
                self.settings.sync_history_batch_size or self.settings.sync_batch_size,
            ),
        ):
            async with self.database.sessions() as session:
                if entities == CURRENT_ENTITIES:
                    rows = await self.current_rows(session, limit)
                else:
                    rows = await session.scalars(
                        self.ready()
                        .where(SyncOutbox.entity.in_(entities))
                        .order_by(
                            case((SyncOutbox.entity == "worker_runtime", 0), else_=1), SyncOutbox.id
                        )
                        .limit(limit)
                    )
                batch = [self.serialize(row) for row in rows]
                cursor = rows[-1].coalesce_key if entities == CURRENT_ENTITIES and rows else None
            deferred = await self.send(call, batch) or deferred
            if entities == CURRENT_ENTITIES and cursor:
                self.current_cursor = cursor
        async with self.database.sessions() as session, session.begin():
            state = await session.get(SyncState, 1)
            state.last_sync_at = datetime.now(UTC)
            state.failures = 0
            state.last_error = (
                "Sync records deferred; metadata dependency or validation requires retry"
                if deferred
                else None
            )
        self.failures = 0

    async def current_rows(self, session: AsyncSession, limit: int) -> list[SyncOutbox]:
        # Replacement changes the sequence. Sorting only by that sequence can repeatedly
        # select the same first Tags when all Tags update faster than sync. Rotate stable
        # keys instead; no per-Tag request or full table load is needed.
        query = self.ready().where(SyncOutbox.entity.in_(CURRENT_ENTITIES))
        order = (SyncOutbox.coalesce_key, SyncOutbox.id)
        if self.current_cursor is None:
            return list(await session.scalars(query.order_by(*order).limit(limit)))
        rows = list(
            await session.scalars(
                query.where(SyncOutbox.coalesce_key > self.current_cursor)
                .order_by(*order)
                .limit(limit)
            )
        )
        if len(rows) < limit:
            rows.extend(
                await session.scalars(
                    query.where(
                        or_(
                            SyncOutbox.coalesce_key <= self.current_cursor,
                            SyncOutbox.coalesce_key.is_(None),
                        )
                    )
                    .order_by(*order)
                    .limit(limit - len(rows))
                )
            )
        return rows

    @staticmethod
    def ready() -> Select[tuple[SyncOutbox]]:
        return select(SyncOutbox).where(
            or_(SyncOutbox.retry_at.is_(None), SyncOutbox.retry_at <= datetime.now(UTC))
        )

    @staticmethod
    def serialize(row: SyncOutbox) -> dict[str, Any]:
        return {
            "event_id": row.event_id,
            "sequence": row.id,
            "entity": row.entity,
            "operation": row.operation,
            "payload": row.payload,
        }

    async def send(
        self, call: Callable[..., Awaitable[dict[str, Any]]], events: list[dict[str, Any]]
    ) -> bool:
        if not events:
            return False
        result = await call("POST", "events", json={"version": 1, "events": events})
        ids = set(result["acknowledged"])
        deferred = {item["event_id"] for item in result.get("deferred", [])}
        sent = {event["event_id"] for event in events}
        if not (ids | deferred).issubset(sent) or ids & deferred:
            raise ValueError("Invalid Cloud acknowledgement")
        async with self.database.sessions() as session, session.begin():
            if ids:
                # Worker replacement changes UUID atomically. ACK of an old upload cannot
                # delete a newer pending value, even if it arrived while HTTP was in flight.
                await session.execute(delete(SyncOutbox).where(SyncOutbox.event_id.in_(ids)))
            if deferred:
                await session.execute(
                    update(SyncOutbox)
                    .where(SyncOutbox.event_id.in_(deferred))
                    .values(
                        retry_at=datetime.now(UTC)
                        + timedelta(seconds=max(5, self.settings.sync_interval_seconds * 3))
                    )
                )
        return bool(deferred)

    async def step(self) -> float:
        try:
            await self.cycle()
            return self.settings.sync_interval_seconds
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failures += 1
            # Do not log HTTP exception repr (URL, headers or remote content can contain secrets).
            message = "Cloud synchronization failed: " + type(exc).__name__
            logger.warning(message)
            try:
                async with self.database.sessions() as session, session.begin():
                    state = await session.get(SyncState, 1)
                    state.last_error = message
                    state.failures = self.failures
            except Exception:
                logger.error("Could not persist sync failure state")
            return min(
                self.settings.sync_backoff_max_seconds,
                self.settings.sync_interval_seconds * 2 ** min(self.failures, 10),
            )

    async def run(self, stop: asyncio.Event) -> None:
        try:
            while not stop.is_set():
                started = asyncio.get_running_loop().time()
                delay = await self.step()
                elapsed = asyncio.get_running_loop().time() - started
                try:
                    await asyncio.wait_for(stop.wait(), max(0, delay - elapsed))
                except TimeoutError:
                    pass
        finally:
            await self.http.aclose()
