import asyncio
import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from test_configuration import create, setup_tag

from app.models import TagCurrentValue
from app.schemas.telemetry import CurrentValueRead, TagValueEvent, utc
from app.services.current_values import (
    Reading,
    get_current,
    is_stale,
    mark_stale,
    upsert_current,
)
from app.services.live import LiveHub, NotificationListener
from app.worker.polling import collect_one, load_configuration, reconcile_disabled
from app.worker.scheduler import PollScheduler
from app.worker.simulator import SimulatorSource
from app.worker.sources import PollTag


def config(**changes) -> PollTag:
    now = datetime.now(UTC)
    return replace(
        PollTag(
            1, "float32", 1000, Decimal(1), Decimal(0), None, None, True, now, now, now
        ),
        **changes,
    )


@pytest.mark.anyio
async def test_upsert_latest_value_and_error_recovery(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    now = datetime.now(UTC)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal("12.5"), now, "12.5")
        )
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], quality="COMM_ERROR", error="Source unavailable"
        )
    async with database_sessions() as session:
        current = await get_current(session, tag["id"])
        assert current.value_numeric == Decimal("12.5")
        assert utc(current.source_timestamp) == now
        assert current.quality == "COMM_ERROR" and current.revision == 2
    async with database_sessions() as session, session.begin():
        await upsert_current(session, tag["id"], reading=Reading(Decimal("13.5"), now))
    async with database_sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(TagCurrentValue)) == 1
        )
        current = await get_current(session, tag["id"])
        assert current.value_numeric == Decimal("13.5")
        assert (
            current.quality == "GOOD"
            and current.error is None
            and current.revision == 3
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "value,column",
    [
        (False, "value_boolean"),
        (True, "value_boolean"),
        (Decimal("42.75"), "value_numeric"),
        ("future text", "value_text"),
    ],
)
async def test_typed_values(
    api: AsyncClient, database_sessions, value, column: str
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(value, datetime.now(UTC))
        )
    response = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert response[column] == (float(value) if isinstance(value, Decimal) else value)
    assert (
        sum(
            response[field] is not None
            for field in ("value_numeric", "value_boolean", "value_text")
        )
        == 1
    )


@pytest.mark.anyio
async def test_snapshot_filters_waiting_and_disabled(
    api: AsyncClient, database_sessions
) -> None:
    first = await setup_tag(api)
    second = await create(
        api,
        "tags",
        name="Second",
        key="second",
        device_id=first["device_id"],
        data_type="bool",
        register_type="coil",
        address=0,
        enabled=False,
    )
    waiting = (await api.get(f"/api/tags/{first['id']}/value")).json()
    assert waiting["quality"] is None and waiting["revision"] == 0
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, first["id"], reading=Reading(Decimal(5), datetime.now(UTC))
        )
        await reconcile_disabled(session, await load_configuration(session))
    assert (await api.get(f"/api/tags/{second['id']}/value")).json()[
        "quality"
    ] == "DISABLED"
    for query in (f"tag_id={first['id']}", "quality=GOOD", "enabled=true"):
        data = (await api.get(f"/api/tags/values?{query}")).json()
        assert len(data) == 1 and data[0]["tag_id"] == first["id"]
    assert (
        len((await api.get(f"/api/tags/values?device_id={first['device_id']}")).json())
        == 2
    )
    page = (
        await api.get(f"/api/tags/values?after_tag_id={first['id']}&limit=1")
    ).json()
    assert page[0]["tag_id"] == second["id"]
    assert (await api.get("/api/tags/values?device_id=999")).json() == []
    assert (await api.get("/api/tags/values?quality=INVALID")).status_code == 422
    assert (await api.get("/api/tags/999/value")).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize("level", ["tag", "device", "connection"])
async def test_disabled_configuration_never_collects(
    api: AsyncClient, database_sessions, level: str
) -> None:
    tag = await setup_tag(api)
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    resource, identifier = {
        "tag": ("tags", tag["id"]),
        "device": ("devices", device["id"]),
        "connection": ("connections", device["connection_id"]),
    }[level]
    async with database_sessions() as session:
        old_config = (await load_configuration(session))[0]
    assert (
        await api.patch(f"/api/{resource}/{identifier}", json={"enabled": False})
    ).status_code == 200
    async with database_sessions() as session, session.begin():
        # In-flight old source data is rejected by the revision check.
        await collect_one(session, SimulatorSource(), old_config)
        tags = await load_configuration(session)
        assert not tags[0].enabled
        await reconcile_disabled(session, tags)
    async with database_sessions() as session:
        current = await get_current(session, tag["id"])
        assert current.quality == "DISABLED" and current.value_numeric is None
        revision = current.revision
    async with database_sessions() as session, session.begin():
        await reconcile_disabled(session, await load_configuration(session))
    assert (await api.get(f"/api/tags/{tag['id']}/value")).json()[
        "revision"
    ] == revision


@pytest.mark.anyio
async def test_configuration_change_invalidates_and_delete_removes_derived_value(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(5), datetime.now(UTC))
        )
    assert (
        await api.patch(f"/api/tags/{tag['id']}", json={"scale": 2})
    ).status_code == 200
    current = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert current["quality"] == "BAD" and current["value_numeric"] is None
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    async with database_sessions() as session:
        assert (
            await session.scalar(select(func.count()).select_from(TagCurrentValue)) == 0
        )


@pytest.mark.parametrize(
    "data_type",
    ["uint16", "int16", "uint32", "int32", "uint64", "int64", "float32", "float64"],
)
@pytest.mark.anyio
async def test_simulator_bounds_and_gradual_changes(data_type: str) -> None:
    tag = config(data_type=data_type, min_value=Decimal(10), max_value=Decimal(100))
    source = SimulatorSource(rng=random.Random(42))
    values = [(await source.read(tag)).value for _ in range(100)]
    assert all(10 <= value <= 100 for value in values)
    assert len(set(values)) > 1
    assert max(abs(a - b) for a, b in zip(values, values[1:])) <= 2


@pytest.mark.parametrize(
    "scale,offset",
    [
        (Decimal(2), Decimal(10)),
        (Decimal(-2), Decimal(200)),
        (Decimal("0.1"), Decimal(-1)),
        (Decimal(0), Decimal(25)),
    ],
)
@pytest.mark.anyio
async def test_scale_offset_engineering_limits(scale: Decimal, offset: Decimal) -> None:
    source = SimulatorSource(rng=random.Random(1))
    tag = config(
        data_type="uint16",
        scale=scale,
        offset=offset,
        min_value=Decimal(20),
        max_value=Decimal(30),
    )
    for _ in range(20):
        reading = await source.read(tag)
        assert reading.value == Decimal(reading.raw_value) * scale + offset
        assert 20 <= reading.value <= 30


@pytest.mark.anyio
async def test_boolean_simulation_and_limits() -> None:
    source = SimulatorSource(rng=random.Random(42))
    values = {(await source.read(config(data_type="bool"))).value for _ in range(30)}
    assert values == {False, True}
    assert (
        await source.read(config(data_type="bool", max_value=Decimal(0)))
    ).value is False


@pytest.mark.anyio
async def test_impossible_simulator_limits_become_bad(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api, min_value=0.1, max_value=0.2)
    async with database_sessions() as session, session.begin():
        await collect_one(
            session, SimulatorSource(), (await load_configuration(session))[0]
        )
    response = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert response["quality"] == "BAD" and response["error"]


@pytest.mark.anyio
async def test_simulated_failure_preserves_success(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(10), datetime.now(UTC))
        )
    async with database_sessions() as session, session.begin():
        await collect_one(
            session,
            SimulatorSource(failure_probability=1),
            (await load_configuration(session))[0],
        )
    response = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert response["quality"] == "COMM_ERROR" and response["value_numeric"] == 10


def test_scheduler_intervals_refresh_disable_and_no_catchup() -> None:
    scheduler = PollScheduler()
    first, second = config(), config(id=2, poll_interval_ms=5000)
    assert scheduler.refresh([first, second], 10) == {1, 2}
    assert scheduler.due(10) == [first, second]
    scheduler.completed(first, 10)
    scheduler.completed(second, 10)
    assert scheduler.due(10.9) == []
    assert scheduler.due(11) == [first]
    scheduler.completed(first, 100)
    assert scheduler.next_due[first.id] == 101
    assert scheduler.refresh([first, replace(second, enabled=False)], 20) == {2}
    assert second.id not in scheduler.tags
    scheduler.refresh([replace(first, poll_interval_ms=2000)], 30)
    assert scheduler.due(30)[0].poll_interval_ms == 2000
    assert scheduler.delay(30, 31) > 0


@pytest.mark.parametrize(
    "interval,age,stale",
    [(1000, 2.9, False), (1000, 3.1, True), (10000, 5, False), (10000, 31, True)],
)
def test_stale_depends_on_interval(interval: int, age: float, stale: bool) -> None:
    now = datetime.now(UTC)
    assert is_stale(now - timedelta(seconds=age), interval, 3, now) is stale


@pytest.mark.anyio
async def test_stale_preserves_value_and_error_states(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    now = datetime.now(UTC)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(7), now - timedelta(seconds=10))
        )
    async with database_sessions() as session, session.begin():
        assert await mark_stale(session, 3, now) == 1
    async with database_sessions() as session:
        value = await get_current(session, tag["id"])
        assert (
            value.quality == "STALE"
            and value.value_numeric == 7
            and value.revision == 2
        )
    async with database_sessions() as session, session.begin():
        assert await mark_stale(session, 3, now) == 0
        await upsert_current(session, tag["id"], quality="COMM_ERROR", error="Failure")
    async with database_sessions() as session, session.begin():
        assert await mark_stale(session, 3, now) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fields",
    [
        {"quality": "UNKNOWN"},
        {"quality": "GOOD"},
        {"quality": "BAD", "value_numeric": 1, "value_boolean": True},
        {"quality": "BAD", "revision": 0},
    ],
)
async def test_current_value_database_constraints(
    api: AsyncClient, database_sessions, fields
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                insert(TagCurrentValue).values(tag_id=tag["id"], **fields)
            )
            await session.commit()


@pytest.mark.anyio
async def test_current_value_fk_and_primary_key(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session, session.begin():
        await upsert_current(session, tag["id"], quality="DISABLED")
    for identifier in (tag["id"], 999):
        async with database_sessions() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    insert(TagCurrentValue).values(
                        tag_id=identifier, quality="DISABLED"
                    )
                )
                await session.commit()


def test_payload_numeric_and_exact_representation() -> None:
    value = CurrentValueRead(
        tag_id=1,
        key="test",
        name="Test",
        device_id=1,
        data_type="uint64",
        unit=None,
        enabled=True,
        effective_enabled=True,
        value_numeric=Decimal(2**64 - 1),
        quality="GOOD",
        source_timestamp=datetime.now(UTC),
        revision=1,
    )
    payload = TagValueEvent(data=value).model_dump(mode="json")
    assert payload["type"] == "tag_value"
    assert payload["data"]["value_numeric"] == 2**64 - 1
    assert payload["data"]["value_numeric_exact"] == str(2**64 - 1)


@pytest.mark.anyio
async def test_hub_fanout_and_overflow_requires_resync() -> None:
    hub = LiveHub(queue_size=1)
    first, second = hub.subscribe(), hub.subscribe()
    hub.publish({"type": "heartbeat"})
    assert (await first.get())["type"] == "heartbeat"
    hub.publish({"type": "tag_deleted", "tag_id": 1})
    assert (await second.get())["type"] == "resync_required"
    assert (await first.get())["type"] == "tag_deleted"
    hub.unsubscribe(first)
    hub.unsubscribe(second)
    assert not hub.clients


@pytest.mark.anyio
async def test_listener_reconnects_and_signals_snapshot(monkeypatch) -> None:
    hub = LiveHub()
    queue = hub.subscribe()
    database, connection = AsyncMock(), AsyncMock()
    connection.terminate = lambda: None
    connect = AsyncMock(side_effect=[OSError("Database interrupted"), connection])
    listener = NotificationListener(database, hub, connect)
    listener.dispatch = AsyncMock()
    real_sleep = asyncio.sleep

    async def short_sleep(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr("app.services.live.asyncio.sleep", short_sleep)
    task = asyncio.create_task(listener.run())
    try:
        async with asyncio.timeout(2):
            while (await queue.get()).get("type") != "resync_required":
                pass
        assert connect.await_count == 2 and hub.ready
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
