"""Independent HTTPS store-and-forward. No device access; no interactive user session."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import delete, or_, select, update

from app.core.config import Settings
from app.db.session import Database
from app.models import SyncOutbox, SyncState
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

    async def cycle(self) -> None:
        async with self.database.sessions() as session:
            state = await session.get(SyncState, 1)
            if not state or state.mode != "edge":
                raise ValueError("Sync requires initialized Edge database")
            identity = state.installation_id
        headers = {
            "Authorization": "Bearer " + self.settings.sync_token.get_secret_value(),
            "X-Edge-ID": identity,
        }

        async def call(method, path, **kwargs):
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
        async with self.database.sessions() as session:
            # Reserve capacity for each lane; old history cannot starve control results or vice versa.
            rows = []
            per_lane = max(1, self.settings.sync_batch_size // 6)
            for priority in (0, 1, 2, 3, 4, 9):
                rows.extend(
                    await session.scalars(
                        select(SyncOutbox)
                        .where(
                            SyncOutbox.priority == priority,
                            or_(
                                SyncOutbox.retry_at.is_(None),
                                SyncOutbox.retry_at <= datetime.now(UTC),
                            ),
                        )
                        .order_by(SyncOutbox.id)
                        .limit(per_lane)
                    )
                )
            rows = rows[: self.settings.sync_batch_size]
            events = [
                {
                    "event_id": r.event_id,
                    "sequence": r.id,
                    "entity": r.entity,
                    "operation": r.operation,
                    "payload": r.payload,
                }
                for r in rows
            ]
        if events:
            result = await call("POST", "events", json={"version": 1, "events": events})
            ids = set(result["acknowledged"])
            if not ids.issubset({e["event_id"] for e in events}):
                raise ValueError("Invalid Cloud acknowledgement")
            async with self.database.sessions() as session, session.begin():
                if ids:
                    await session.execute(delete(SyncOutbox).where(SyncOutbox.event_id.in_(ids)))
                deferred = [item["event_id"] for item in result.get("deferred", [])]
                if deferred:
                    await session.execute(
                        update(SyncOutbox)
                        .where(SyncOutbox.event_id.in_(deferred))
                        .values(
                            retry_at=datetime.now(UTC)
                            + timedelta(seconds=max(5, self.settings.sync_interval_seconds * 3))
                        )
                    )
                state = await session.get(SyncState, 1)
                state.last_sync_at = datetime.now(UTC)
                state.failures = 0
                state.last_error = (
                    "Sync records deferred; metadata dependency or validation requires retry"
                    if result.get("deferred")
                    else None
                )
        else:
            async with self.database.sessions() as session, session.begin():
                state = await session.get(SyncState, 1)
                state.last_sync_at = datetime.now(UTC)
                state.last_error = None
                state.failures = 0
        self.failures = 0

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
                delay = await self.step()
                try:
                    await asyncio.wait_for(stop.wait(), delay)
                except TimeoutError:
                    pass
        finally:
            await self.http.aclose()
