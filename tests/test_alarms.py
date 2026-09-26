from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from test_automation import sample
from test_configuration import create, setup_tag

from app.core.config import Settings
from app.models import AlarmEvent, NotificationDelivery
from app.services.alarms import ALARM_CHANNEL
from app.services.live import LiveHub, NotificationListener
from app.worker.alarms import AlarmEngine
from app.worker.notifications import NotificationSender, send_telegram

pytestmark = pytest.mark.anyio


def engine(sessions):
    return AlarmEngine(
        SimpleNamespace(sessions=sessions),
        Settings(postgres_password="test", telemetry_source="simulator"),
    )


async def rule(api, tag, **changes):
    return await create(
        api,
        "alarms/rules",
        name="Test abnormal condition",
        tag_id=tag["id"],
        **{"operator": ">", "value": "30", "severity": "CRITICAL", "enabled": True, **changes},
    )


async def events(api):
    return (await api.get("/api/alarms/events")).json()


async def test_crud_and_filters(api):
    tag = await setup_tag(api)
    r = await rule(api, tag)
    assert (await api.get(f"/api/alarms/rules/{r['id']}")).json()["name"] == r["name"]
    assert (await api.patch(f"/api/alarms/rules/{r['id']}", json={"enabled": False})).json()[
        "enabled"
    ] is False
    assert len((await api.get("/api/alarms/rules")).json()) == 1
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409
    assert (await api.delete(f"/api/alarms/rules/{r['id']}")).status_code == 204
    assert (await api.get(f"/api/alarms/rules/{r['id']}")).status_code == 404
    assert (
        await api.get("/api/alarms/events?from=2026-01-02T00:00:00Z&to=2026-01-01T00:00:00Z")
    ).status_code == 422
    assert (await api.get("/api/alarms/events?from=2026-01-01T00:00:00")).status_code == 422
    assert (await api.get("/api/alarms/events?limit=501")).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"value": True},
        {"tag_id": 999},
        {"severity": "urgent"},
        {"operator": "contains"},
        {"for_duration_ms": -1},
        {"hysteresis": -1},
        {"operator": "==", "hysteresis": 1},
        {"value": "NaN"},
        {"name": " "},
    ],
)
async def test_invalid_rule(api, changes):
    tag = await setup_tag(api)
    payload = {"name": "Rule", "tag_id": tag["id"], "operator": ">", "value": "30", **changes}
    assert (await api.post("/api/alarms/rules", json=payload)).status_code == 422


async def test_duration_hysteresis_ack_clear_reactivation_outbox(api, database_sessions):
    tag = await setup_tag(api, poll_interval_ms=5000)
    r = await rule(api, tag, for_duration_ms=2000, hysteresis="2", notification_enabled=True)
    worker = engine(database_sessions)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 31, now)
    await worker.tick(now)
    assert await events(api) == []
    await worker.tick(now + timedelta(seconds=1))
    assert await events(api) == []
    await worker.tick(now + timedelta(seconds=2))
    e = (await events(api))[0]
    assert e["state"] == "ACTIVE" and Decimal(e["value_numeric"]) == 31
    assert (await api.get("/api/alarms/summary")).json() == {"active": 1, "critical": 1}
    assert (
        len(
            (
                await api.get(
                    f"/api/alarms/events?active=true&severity=CRITICAL&rule_id={r['id']}&tag_id={tag['id']}"
                )
            ).json()
        )
        == 1
    )
    assert (await api.get("/api/alarms/events?severity=INFO")).json() == []
    ack = await api.post(f"/api/alarms/events/{e['id']}/acknowledge")
    assert ack.json()["state"] == "ACKNOWLEDGED"
    assert (await api.post(f"/api/alarms/events/{e['id']}/acknowledge")).status_code == 409
    await sample(database_sessions, tag, 29, now + timedelta(seconds=3))
    await worker.tick(now + timedelta(seconds=3))
    assert (await events(api))[0]["state"] == "ACKNOWLEDGED"
    await sample(database_sessions, tag, 28, now + timedelta(seconds=4))
    await worker.tick(now + timedelta(seconds=4))
    assert (await events(api))[0]["state"] == "CLEARED"
    assert (await api.post(f"/api/alarms/events/{e['id']}/acknowledge")).status_code == 409
    await sample(database_sessions, tag, 32, now + timedelta(seconds=5))
    await worker.tick(now + timedelta(seconds=5))
    await worker.tick(now + timedelta(seconds=7))
    await worker.tick(now + timedelta(seconds=8))
    assert len(await events(api)) == 2
    async with database_sessions() as session:
        assert len(list(await session.scalars(select(NotificationDelivery)))) == 2
    assert (await api.delete(f"/api/alarms/rules/{r['id']}")).status_code == 409


@pytest.mark.parametrize("quality", ["BAD", "STALE", "COMM_ERROR", "DISABLED"])
async def test_invalid_quality_does_not_activate_or_clear(api, database_sessions, quality):
    tag = await setup_tag(api)
    await rule(api, tag)
    worker = engine(database_sessions)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 31, now, quality)
    await worker.tick(now)
    assert await events(api) == []
    await sample(database_sessions, tag, 31, now)
    await worker.tick(now)
    await sample(database_sessions, tag, 0, now, quality)
    await worker.tick(now)
    assert (await events(api))[0]["state"] == "ACTIVE"


async def test_restart_timer_false_spike_and_source(api, database_sessions):
    tag = await setup_tag(api, poll_interval_ms=5000)
    await rule(api, tag, for_duration_ms=2000)
    now = datetime.now(UTC)
    worker = engine(database_sessions)
    await sample(database_sessions, tag, 31, now, source="modbus_tcp")
    await worker.tick(now)
    assert await events(api) == []
    await sample(database_sessions, tag, 31, now)
    await worker.tick(now)
    await sample(database_sessions, tag, 29, now + timedelta(seconds=1))
    await worker.tick(now + timedelta(seconds=1))
    await sample(database_sessions, tag, 31, now + timedelta(seconds=2))
    await worker.tick(now + timedelta(seconds=2))
    worker = engine(database_sessions)
    await worker.recover()
    await worker.tick(now + timedelta(seconds=3))
    await worker.tick(now + timedelta(seconds=4))
    assert await events(api) == []
    await worker.tick(now + timedelta(seconds=5))
    assert len(await events(api)) == 1
    worker = engine(database_sessions)
    await worker.recover()
    await worker.tick(now + timedelta(seconds=6))
    assert len(await events(api)) == 1


@pytest.mark.parametrize(
    "op,value", [(">", 31), (">=", 30), ("<", 29), ("<=", 30), ("==", 30), ("!=", 31)]
)
async def test_numeric_operators(api, database_sessions, op, value):
    tag = await setup_tag(api)
    await rule(api, tag, operator=op)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, value, now)
    await engine(database_sessions).tick(now)
    assert len(await events(api)) == 1


@pytest.mark.parametrize("op,value", [("==", True), ("!=", False)])
async def test_boolean(api, database_sessions, op, value):
    tag = await setup_tag(api, data_type="bool", register_type="coil")
    await rule(api, tag, operator=op, value=value)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, True, now)
    await engine(database_sessions).tick(now)
    assert (await events(api))[0]["value_boolean"] is True
    assert (
        await api.post(
            "/api/alarms/rules",
            json={"name": "bad", "tag_id": tag["id"], "operator": ">", "value": True},
        )
    ).status_code == 422


async def test_reload_disable_and_websocket(api, database_sessions):
    tag = await setup_tag(api)
    r = await rule(api, tag, enabled=False)
    worker = engine(database_sessions)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 31, now)
    await worker.tick(now)
    assert await events(api) == []
    await api.patch(f"/api/alarms/rules/{r['id']}", json={"enabled": True})
    await sample(database_sessions, tag, 31, now + timedelta(seconds=3))
    await worker.tick(now + timedelta(seconds=3))
    e = (await events(api))[0]
    hub = LiveHub()
    queue = hub.subscribe()
    listener = NotificationListener(SimpleNamespace(sessions=database_sessions), hub, None)
    listener.notified(None, 1, ALARM_CHANNEL, str(e["id"]))
    await listener.dispatch()
    payload = queue.get_nowait()
    assert payload["type"] == "alarm_event" and payload["data"]["state"] == "ACTIVE"
    await api.patch(f"/api/alarms/rules/{r['id']}", json={"enabled": False})
    assert (await events(api))[0]["clear_reason"] == "Rule configuration changed"


async def test_unique_open_event_constraint(api, database_sessions):
    tag = await setup_tag(api)
    r = await rule(api, tag)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 31, now)
    await engine(database_sessions).tick(now)
    async with database_sessions() as session:
        session.add(
            AlarmEvent(
                rule_id=r["id"],
                tag_id=tag["id"],
                name="x",
                tag_name="x",
                condition=">30",
                severity="WARNING",
                state="ACTIVE",
                value_numeric=32,
                activated_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize(
    "result", [None, "Telegram request failed or timed out; delivery may be uncertain"]
)
async def test_telegram_success_failure_no_duplicate(api, database_sessions, monkeypatch, result):
    assert (await api.post("/api/notifications/telegram/test")).status_code == 422
    assert (
        await api.patch("/api/notifications/telegram/destination", json={"chat_id": "-123"})
    ).status_code == 200
    assert (await api.post("/api/notifications/telegram/test")).status_code == 202
    send = Mock(return_value=result)
    monkeypatch.setattr("app.worker.notifications.send_telegram", send)
    sender = NotificationSender(
        SimpleNamespace(sessions=database_sessions),
        Settings(
            postgres_password="test", telegram_enabled=True, telegram_bot_token="secret-test-token"
        ),
    )
    assert await sender.tick()
    assert not await sender.tick()
    send.assert_called_once()
    row = (await api.get("/api/notifications/telegram/deliveries")).json()[0]
    assert row["status"] == ("FAILED" if result else "SENT")
    assert "secret-test-token" not in str(row)


async def test_telegram_disabled_expired_restart(database_sessions, monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.worker.notifications.send_telegram", send)
    async with database_sessions() as session, session.begin():
        session.add_all(
            [
                NotificationDelivery(
                    kind="TEST",
                    chat_id="1",
                    message="test",
                    status="PENDING",
                    created_at=datetime.now(UTC),
                ),
                NotificationDelivery(
                    kind="TEST",
                    chat_id="1",
                    message="test",
                    status="SENDING",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
    sender = NotificationSender(
        SimpleNamespace(sessions=database_sessions), Settings(postgres_password="test")
    )
    await sender.recover()
    await sender.tick()
    send.assert_not_called()
    async with database_sessions() as session:
        assert set(await session.scalars(select(NotificationDelivery.status))) == {
            "SKIPPED",
            "FAILED",
        }


@pytest.mark.parametrize("failure", [TimeoutError("secret"), ValueError("secret")])
async def test_telegram_http_sanitized(monkeypatch, failure, caplog):
    opener = Mock()
    opener.open.side_effect = failure
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    error = send_telegram("secret", "123", "test", 1)
    assert error and "secret" not in error and "secret" not in caplog.text


@pytest.mark.parametrize("resource", ["tags", "devices", "connections"])
async def test_disabled_configuration(api, database_sessions, resource):
    tag = await setup_tag(api)
    await rule(api, tag)
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    identifier = {
        "tags": tag["id"],
        "devices": tag["device_id"],
        "connections": device["connection_id"],
    }[resource]
    await api.patch(f"/api/{resource}/{identifier}", json={"enabled": False})
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 31, now)
    await engine(database_sessions).tick(now)
    assert await events(api) == []


async def test_stale_timestamp_low_hysteresis_and_timer_reset(api, database_sessions):
    tag = await setup_tag(api, poll_interval_ms=1000)
    await rule(api, tag, operator="<", value="30", hysteresis="2", for_duration_ms=1000)
    worker = engine(database_sessions)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 29, now - timedelta(seconds=10))
    await worker.tick(now)
    assert not await events(api)
    await sample(database_sessions, tag, 29, now)
    await worker.tick(now)
    await sample(database_sessions, tag, 29, now + timedelta(milliseconds=500), "COMM_ERROR")
    await worker.tick(now + timedelta(milliseconds=500))
    await sample(database_sessions, tag, 29, now + timedelta(seconds=1))
    await worker.tick(now + timedelta(seconds=1))
    assert not await events(api)
    await worker.tick(now + timedelta(seconds=2))
    assert len(await events(api)) == 1
    await sample(database_sessions, tag, 31, now + timedelta(seconds=3))
    await worker.tick(now + timedelta(seconds=3))
    assert (await events(api))[0]["state"] == "ACTIVE"
    await sample(database_sessions, tag, 32, now + timedelta(seconds=4))
    await worker.tick(now + timedelta(seconds=4))
    assert (await events(api))[0]["state"] == "CLEARED"


async def test_expired_notifications_never_send(database_sessions, monkeypatch):
    send = Mock()
    monkeypatch.setattr("app.worker.notifications.send_telegram", send)
    async with database_sessions() as session, session.begin():
        session.add(
            NotificationDelivery(
                kind="TEST",
                chat_id="1",
                message="old",
                status="PENDING",
                created_at=datetime.now(UTC) - timedelta(minutes=6),
            )
        )
    sender = NotificationSender(
        SimpleNamespace(sessions=database_sessions),
        Settings(postgres_password="test", telegram_enabled=True, telegram_bot_token="test-secret"),
    )
    await sender.tick()
    send.assert_not_called()
    async with database_sessions() as session:
        row = await session.scalar(select(NotificationDelivery))
        assert row.status == "SKIPPED" and "expired" in row.error


async def test_http_success_uses_post_plaintext_and_no_redirect(monkeypatch):
    import json

    response = Mock()
    response.read.return_value = b'{"ok":true}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: opener)
    assert send_telegram("secret", "-123", "<name> & value", 3) is None
    request = opener.open.call_args.args[0]
    assert request.method == "POST" and opener.open.call_args.kwargs["timeout"] == 3
    assert json.loads(request.data) == {"chat_id": "-123", "text": "<name> & value"}


@pytest.mark.parametrize(
    "zone, expected",
    [
        ("UTC", "26.09.2026 15:10:52 (UTC)"),
        ("Asia/Yerevan", "26.09.2026 19:10:52 (Asia/Yerevan)"),
        ("Europe/Berlin", "26.09.2026 17:10:52 (Europe/Berlin)"),
    ],
)
async def test_readable_telegram_timestamp(zone, expected):
    from app.services.alarms import telegram_timestamp

    instant = datetime(2026, 9, 26, 15, 10, 52, 958491, tzinfo=UTC)
    assert telegram_timestamp(instant, zone) == expected
    assert instant.hour == 15


async def test_invalid_telegram_timezone():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="valid IANA"):
        Settings(postgres_password="test", telegram_timezone="Invalid/Zone")


async def test_notification_uses_worker_timezone(api, database_sessions):
    tag = await setup_tag(api)
    await rule(api, tag, notification_enabled=True)
    now = datetime(2026, 9, 26, 15, 10, 52, 958491, tzinfo=UTC)
    await sample(database_sessions, tag, 31, now)
    worker = AlarmEngine(
        SimpleNamespace(sessions=database_sessions),
        Settings(
            postgres_password="test", telemetry_source="simulator", telegram_timezone="Asia/Yerevan"
        ),
    )
    await worker.tick(now)
    async with database_sessions() as session:
        delivery = await session.scalar(select(NotificationDelivery))
        assert "Activated: 26.09.2026 19:10:52 (Asia/Yerevan)" in delivery.message
