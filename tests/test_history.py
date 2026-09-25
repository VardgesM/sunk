import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_configuration import setup_tag

from app.core.config import Settings
from app.models import TagCurrentValue, TagHistory
from app.services import history_retention, history_writer
from app.services.current_values import Reading, mark_stale, upsert_current
from app.services.history_retention import cleanup_batch

pytestmark = pytest.mark.anyio
Sessions = async_sessionmaker[AsyncSession]
NOW = datetime.now(UTC)


async def sample(
    sessions: Sessions,
    tag_id: int,
    seconds: float,
    value: Decimal | bool | str = Decimal(10),
    quality: str = "GOOD",
) -> None:
    now = NOW + timedelta(seconds=seconds)
    async with sessions() as session, session.begin():
        await upsert_current(
            session,
            tag_id,
            now=now,
            quality=quality,
            reading=Reading(value, now) if quality == "GOOD" else None,
        )


async def rows(sessions: Sessions) -> list[TagHistory]:
    async with sessions() as session:
        return list(
            await session.scalars(
                select(TagHistory).order_by(TagHistory.recorded_at, TagHistory.id)
            )
        )


@pytest.mark.parametrize(
    "patch,valid",
    [
        ({"history_mode": "every_sample"}, True),
        ({"history_mode": "unknown"}, False),
        ({"history_mode": "fixed_interval"}, False),
        ({"history_mode": "fixed_interval", "history_interval_ms": 1000}, True),
        ({"history_mode": "fixed_interval", "history_interval_ms": 999}, False),
        ({"history_mode": "fixed_interval", "history_interval_ms": 0}, False),
        ({"history_mode": "on_change"}, False),
        ({"history_mode": "on_change", "history_change_threshold": 0}, True),
        ({"history_mode": "on_change", "history_change_threshold": -1}, False),
        ({"history_retention_days": 0}, False),
        ({"history_retention_days": -1}, False),
        ({"history_retention_days": 30}, True),
    ],
)
async def test_history_validation(api: AsyncClient, patch: dict[str, Any], valid: bool) -> None:
    tag = await setup_tag(api)
    response = await api.patch(f"/api/tags/{tag['id']}", json=patch)
    assert response.status_code == (200 if valid else 422), response.text


async def test_merged_interval_validation(api: AsyncClient) -> None:
    tag = await setup_tag(api, history_mode="fixed_interval", history_interval_ms=2000)
    assert (
        await api.patch(f"/api/tags/{tag['id']}", json={"poll_interval_ms": 3000})
    ).status_code == 422


async def test_every_sample_and_disabled_history(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(api, history_enabled=True)
    for i in range(3):
        await sample(database_sessions, tag["id"], i)
    assert len(await rows(database_sessions)) == 3
    await api.patch(f"/api/tags/{tag['id']}", json={"history_enabled": False})
    await sample(database_sessions, tag["id"], 4)
    await sample(database_sessions, tag["id"], 5, quality="COMM_ERROR")
    assert len(await rows(database_sessions)) == 3
    async with database_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TagCurrentValue)) == 1


async def test_fixed_interval_recovers_using_database(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(
        api, history_enabled=True, history_mode="fixed_interval", history_interval_ms=10000
    )
    # Each call is an entirely new session: no process-local state is needed on restart.
    for seconds in (0, 1, 9.999, 10, 19, 20):
        await sample(database_sessions, tag["id"], seconds)
    assert len(await rows(database_sessions)) == 3


async def test_numeric_threshold_from_last_stored_value(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(
        api, history_enabled=True, history_mode="on_change", history_change_threshold=0.2
    )
    for i, value in enumerate(("22.5", "22.55", "22.61", "22.72", "22.92", "22.72")):
        await sample(database_sessions, tag["id"], i, Decimal(value))
    assert [row.value_numeric for row in await rows(database_sessions)] == list(
        map(Decimal, ("22.5", "22.72", "22.92", "22.72"))
    )


async def test_zero_threshold_and_boolean_changes(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(
        api, history_enabled=True, history_mode="on_change", history_change_threshold=0
    )
    for i, value in enumerate((10, 10, 11)):
        await sample(database_sessions, tag["id"], i, Decimal(value))
    assert len(await rows(database_sessions)) == 2
    changed = await api.patch(
        f"/api/tags/{tag['id']}",
        json={"register_type": "coil", "data_type": "bool", "history_change_threshold": None},
    )
    assert changed.status_code == 200
    # A configuration-change BAD marker is written, then boolean states are independent.
    for i, value in enumerate((False, False, True, True, False)):
        await sample(database_sessions, tag["id"], 86400 + i, value)
    assert [
        row.value_boolean for row in await rows(database_sessions) if row.value_boolean is not None
    ] == [False, True, False]


async def test_future_text_equality_and_typed_storage(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(
        api, history_enabled=True, history_mode="on_change", history_change_threshold=0
    )
    for i, value in enumerate(("ready", "ready", "changed")):
        await sample(database_sessions, tag["id"], i, value)
    assert [row.value_text for row in await rows(database_sessions)] == ["ready", "changed"]


async def test_quality_transitions_and_immediate_recovery(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(
        api, history_enabled=True, history_mode="fixed_interval", history_interval_ms=10000
    )
    await sample(database_sessions, tag["id"], 0)
    for i, quality in enumerate(("COMM_ERROR", "COMM_ERROR", "BAD", "DISABLED", "GOOD"), 1):
        await sample(database_sessions, tag["id"], i, quality=quality)
    history = await rows(database_sessions)
    assert [row.quality for row in history] == ["GOOD", "COMM_ERROR", "BAD", "DISABLED", "GOOD"]
    assert all(row.value_numeric is None and row.source_timestamp is None for row in history[1:-1])
    async with database_sessions() as session, session.begin():
        assert await mark_stale(session, 3, NOW + timedelta(seconds=20)) == 1
    assert (await rows(database_sessions))[-1].quality == "STALE"


async def test_history_failure_does_not_rollback_live_value(
    api: AsyncClient,
    database_sessions: Sessions,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tag = await setup_tag(api, history_enabled=True)

    async def invalid_write(session: AsyncSession, *args: Any) -> None:
        await session.execute(insert(TagHistory).values(tag_id=tag["id"], quality="invalid"))

    monkeypatch.setattr(history_writer, "write_history", invalid_write)
    await sample(database_sessions, tag["id"], 0)
    async with database_sessions() as session:
        assert (await session.get(TagCurrentValue, tag["id"])).quality == "GOOD"
    assert not await rows(database_sessions)
    assert "history write failed" in caplog.text


async def test_retention_batched_and_tag_deletion(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(api, history_enabled=True, history_retention_days=1)
    for i in range(5):
        await sample(database_sessions, tag["id"], i)
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409
    async with database_sessions() as session, session.begin():
        assert await cleanup_batch(session, tag["id"], NOW + timedelta(seconds=3), 2) == 2
    assert len(await rows(database_sessions)) == 3
    async with database_sessions() as session, session.begin():
        assert await cleanup_batch(session, tag["id"], NOW + timedelta(seconds=3)) == 1
    assert len(await rows(database_sessions)) == 2
    async with database_sessions() as session, session.begin():
        await cleanup_batch(session, tag["id"], NOW + timedelta(days=1))
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204


@pytest.mark.parametrize(
    "fields",
    [
        {"quality": "UNKNOWN"},
        {"quality": "GOOD", "source_timestamp": NOW},
        {"quality": "GOOD", "value_numeric": 1},
        {"quality": "GOOD", "value_numeric": 1, "value_boolean": True, "source_timestamp": NOW},
        {"quality": "COMM_ERROR", "value_numeric": 1},
        {"quality": "STALE", "tag_id": 99999},
    ],
)
async def test_history_database_constraints(
    api: AsyncClient, database_sessions: Sessions, fields: dict[str, Any]
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(insert(TagHistory).values(**{"tag_id": tag["id"], **fields}))
            await session.commit()


async def test_history_query_order_limits_and_range(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(api, history_enabled=True)
    for i in range(10):
        await sample(database_sessions, tag["id"], i + 0.1, Decimal(i))
    params = {"from": NOW.isoformat(), "to": (NOW + timedelta(seconds=10)).isoformat(), "limit": 3}
    response = await api.get(f"/api/tags/{tag['id']}/history", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 3 and body["total_count"] == 10 and body["truncated"]
    assert [row["value_numeric"] for row in body["points"]] == [0, 1, 2]
    body = (
        await api.get(f"/api/tags/{tag['id']}/history", params={**params, "order": "desc"})
    ).json()
    assert [row["value_numeric"] for row in body["points"]] == [9, 8, 7]
    body = (
        await api.get(
            f"/api/tags/{tag['id']}/history",
            params={**params, "from": (NOW + timedelta(seconds=8)).isoformat()},
        )
    ).json()
    assert body["total_count"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-01-01"},
        {"from": "garbage"},
        {"limit": 0},
        {"limit": 5001},
        {"max_points": 2001},
        {"order": "bad"},
        {"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
        {"from": "2020-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    ],
)
async def test_invalid_queries(api: AsyncClient, params: dict[str, Any]) -> None:
    tag = await setup_tag(api)
    assert (await api.get(f"/api/tags/{tag['id']}/history", params=params)).status_code == 422


async def test_empty_and_unknown_history(api: AsyncClient) -> None:
    tag = await setup_tag(api)
    body = (await api.get(f"/api/tags/{tag['id']}/history")).json()
    assert body["points"] == [] and body["count"] == 0 and not body["downsampled"]
    assert (await api.get("/api/tags/99999/history")).status_code == 404


async def test_sql_downsampling_and_outage_gaps(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(api, history_enabled=True)
    for i in range(10):
        await sample(database_sessions, tag["id"], i + 0.1, Decimal(i))
    params = {
        "from": NOW.isoformat(),
        "to": (NOW + timedelta(seconds=10)).isoformat(),
        "max_points": 2,
    }
    body = (await api.get(f"/api/tags/{tag['id']}/history", params=params)).json()
    assert body["downsampled"] and body["count"] == 2 and body["total_count"] == 10
    assert [p["average"] for p in body["points"]] == [2, 7]
    assert body["points"][0]["minimum"] == 0 and body["points"][0]["maximum"] == 4
    assert body["points"][0]["first_timestamp"] < body["points"][0]["last_timestamp"]
    await sample(database_sessions, tag["id"], 9.9, quality="COMM_ERROR")
    body = (await api.get(f"/api/tags/{tag['id']}/history", params=params)).json()
    assert body["points"][1]["has_invalid"] and body["points"][1]["value_numeric"] is None


async def test_boolean_buckets_never_average_states(
    api: AsyncClient, database_sessions: Sessions
) -> None:
    tag = await setup_tag(api, history_enabled=True, register_type="coil", data_type="bool")
    for i, value in enumerate((False, False, True, False)):
        await sample(database_sessions, tag["id"], i + 0.1, value)
    body = (
        await api.get(
            f"/api/tags/{tag['id']}/history",
            params={
                "from": NOW.isoformat(),
                "to": (NOW + timedelta(seconds=4)).isoformat(),
                "max_points": 2,
            },
        )
    ).json()
    assert body["points"][0]["value_boolean"] is False
    assert body["points"][1]["value_boolean"] is None
    assert all(p["value_numeric"] is None for p in body["points"])


async def test_indexes() -> None:
    assert {index.name for index in TagHistory.__table__.indexes} == {
        "ix_tag_history_tag_id",
        "ix_tag_history_recorded_at",
        "ix_tag_history_tag_recorded",
    }


@pytest.mark.parametrize("fail", [False, True])
async def test_retention_task_and_failure_isolation(
    api: AsyncClient,
    database_sessions: Sessions,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fail: bool,
) -> None:
    tag = await setup_tag(api, history_enabled=True, history_retention_days=1)
    await sample(database_sessions, tag["id"], -3 * 86400)
    await sample(database_sessions, tag["id"], 0)
    stop = asyncio.Event()

    async def cleanup(session: AsyncSession, tag_id: int, cutoff: datetime) -> int:
        stop.set()
        if fail:
            raise RuntimeError("Injected retention error")
        return await cleanup_batch(session, tag_id, cutoff)

    monkeypatch.setattr(history_retention, "cleanup_batch", cleanup)
    await asyncio.wait_for(
        history_retention.retention_loop(
            SimpleNamespace(sessions=database_sessions),
            Settings(postgres_password="test-only"),
            stop,
        ),
        2,
    )
    assert len(await rows(database_sessions)) == (2 if fail else 1)
    if fail:
        assert "History retention failed" in caplog.text
