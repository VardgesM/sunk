"""Durable one-attempt Telegram outbox. Never log request URLs or exception text."""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import Settings
from app.db.session import Database
from app.models import NotificationDelivery

logger = logging.getLogger(__name__)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_telegram(token: str, chat_id: str, message: str, timeout: float) -> str | None:
    # urllib does not log HTTP URLs; redirects are refused so the token stays on Telegram.
    try:
        request = urllib.request.Request(
            "https://api.telegram.org/bot" + token + "/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": message}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            result = json.loads(response.read(65536))
            return None if result.get("ok") is True else "Telegram rejected the message"
    except (TimeoutError, urllib.error.URLError):
        return "Telegram request failed or timed out; delivery may be uncertain"
    except Exception:
        return "Telegram response could not be processed"


class NotificationSender:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database, self.settings = database, settings

    async def recover(self) -> None:
        async with self.database.sessions() as session, session.begin():
            await session.execute(
                update(NotificationDelivery)
                .where(NotificationDelivery.status == "SENDING")
                .values(
                    status="FAILED",
                    error="Worker restarted during delivery; not resent to prevent duplicates",
                    completed_at=datetime.now(UTC),
                )
            )

    async def tick(self) -> bool:
        now = datetime.now(UTC)
        async with self.database.sessions() as session, session.begin():
            delivery = await session.scalar(
                select(NotificationDelivery)
                .where(NotificationDelivery.status == "PENDING")
                .order_by(NotificationDelivery.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if delivery is None:
                return False
            reason = None
            if not self.settings.telegram_enabled:
                reason = "Telegram is disabled in the worker environment"
            elif not self.settings.telegram_bot_token.get_secret_value() or not delivery.chat_id:
                reason = "Telegram token or destination is not configured"
            elif (
                now
                - (
                    delivery.created_at.replace(tzinfo=UTC)
                    if delivery.created_at.tzinfo is None
                    else delivery.created_at
                )
            ) > timedelta(minutes=5):
                reason = "Notification expired after five minutes"
            if reason:
                delivery.status, delivery.error, delivery.completed_at = "SKIPPED", reason, now
                return True
            delivery.status = "SENDING"
            delivery.attempt_count += 1
            identifier, destination, message = delivery.id, delivery.chat_id, delivery.message
        error = await asyncio.to_thread(
            send_telegram,
            self.settings.telegram_bot_token.get_secret_value(),
            destination,
            message,
            self.settings.telegram_timeout_seconds,
        )
        async with self.database.sessions() as session, session.begin():
            delivery = await session.get(NotificationDelivery, identifier)
            delivery.status = "FAILED" if error else "SENT"
            delivery.error, delivery.completed_at = error, datetime.now(UTC)
        if error:
            logger.warning("Telegram delivery failed; delivery_id=%s", identifier)
        return True

    async def run(self, stop: asyncio.Event) -> None:
        recovered = False
        while not stop.is_set():
            try:
                if not recovered:
                    await self.recover()
                    recovered = True
                await self.tick()
            except Exception:
                # Exceptions could contain secret request URLs: never include exception text.
                recovered = False
                logger.error("Notification delivery task failed; retrying database access")
            try:
                await asyncio.wait_for(stop.wait(), 0.5)
            except TimeoutError:
                pass
