import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient
from test_configuration import setup_device, setup_tag
from test_modbus import FakeClient, transport
from test_telemetry import config as base_tag

from app.core.config import Settings
from app.models import ConnectionRuntime, WorkerRuntime
from app.services.current_values import Reading, upsert_current
from app.services.runtime import upsert_runtime
from app.worker import polling
from app.worker.modbus import ConnectionManager
from app.worker.runtime import discover_ports
from app.worker.runtime import test_transport as execute_test
from app.worker.sources import DecodeError

pytestmark = pytest.mark.anyio


async def worker(sessions, mode: str = "modbus", old: bool = False) -> None:
    async with sessions() as session, session.begin():
        await upsert_runtime(
            session,
            WorkerRuntime,
            "id",
            dict(
                id=1,
                mode=mode,
                hostname="test-worker",
                heartbeat_at=datetime.now(UTC) - timedelta(seconds=60 if old else 0),
                serial_ports=[{"device": "discovered-port", "description": "test port"}],
                discovery_error=None,
            ),
        )


async def test_runtime_and_serial_api(api: AsyncClient, database_sessions) -> None:
    assert (await api.get("/api/system/runtime")).json()["mode"] == "unknown"
    assert (await api.get("/api/system/serial-ports")).status_code == 503
    await worker(database_sessions, "simulator")
    assert (await api.get("/api/system/runtime")).json()["mode"] == "simulator"
    discovery = (await api.get("/api/system/serial-ports")).json()
    assert discovery["worker_host"] == "test-worker"
    assert discovery["ports"][0]["device"] == "discovered-port"
    await worker(database_sessions, old=True)
    assert not (await api.get("/api/system/runtime")).json()["alive"]


async def test_connection_diagnostic_handoff_and_result(
    api: AsyncClient, database_sessions
) -> None:
    device = await setup_device(api)
    identifier = device["connection_id"]
    path = f"/api/connections/{identifier}/test"
    assert (await api.post(path)).status_code == 503
    await worker(database_sessions, "simulator")
    assert (await api.post(path)).status_code == 409
    await worker(database_sessions)
    response = await api.post(path)
    assert response.status_code == 202 and response.json()["state"] == "PENDING"
    assert (await api.post(path)).json()["test_id"] == response.json()["test_id"]
    async with database_sessions() as session:
        row = await session.get(ConnectionRuntime, identifier)
        config = transport(id=identifier, version=row.test_configuration_version)
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: FakeClient())
    manager.configure([config])
    await execute_test(
        SimpleNamespace(sessions=database_sessions),
        manager,
        identifier,
        row.test_id,
        row.test_configuration_version,
        row.test_requested_at,
    )
    result = (await api.get(path)).json()
    assert result["state"] == "SUCCEEDED" and "NOT verified" in result["message"]
    assert result["latency_ms"] >= 0
    await api.patch(f"/api/connections/{identifier}", json={"host": "changed.local"})
    assert (await api.get(path)).json()["state"] == "EXPIRED"
    manager.close()


async def test_runtime_status_freshness_and_deletion(api: AsyncClient, database_sessions) -> None:
    device = await setup_device(api)
    identifier = device["connection_id"]
    config = (await api.get(f"/api/connections/{identifier}")).json()
    await worker(database_sessions)
    async with database_sessions() as session, session.begin():
        await upsert_runtime(
            session,
            ConnectionRuntime,
            "connection_id",
            dict(
                connection_id=identifier,
                state="CONNECTED",
                configuration_version=datetime.fromisoformat(config["updated_at"]),
                updated_at=datetime.now(UTC),
                last_success=datetime.now(UTC),
            ),
        )
    assert (await api.get(f"/api/connections/{identifier}/status")).json()["state"] == "CONNECTED"
    await worker(database_sessions, old=True)
    assert (await api.get(f"/api/connections/{identifier}/status")).json()[
        "state"
    ] == "DISCONNECTED"
    await api.patch(f"/api/connections/{identifier}", json={"enabled": False})
    assert (await api.get(f"/api/connections/{identifier}/status")).json()["state"] == "DISABLED"
    assert (await api.delete(f"/api/connections/{identifier}")).status_code == 409
    assert (await api.delete(f"/api/devices/{device['id']}")).status_code == 204
    assert (await api.delete(f"/api/connections/{identifier}")).status_code == 204


async def test_device_states_and_source_provenance(api: AsyncClient, database_sessions) -> None:
    tag = await setup_tag(api)
    path = f"/api/devices/{tag['device_id']}/status"
    await worker(database_sessions)
    assert (await api.get(path)).json()["state"] == "UNKNOWN"
    async with database_sessions() as session, session.begin():
        await upsert_current(session, tag["id"], quality="COMM_ERROR", error="No response")
    assert (await api.get(path)).json()["state"] == "OFFLINE"
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(12), datetime.now(UTC), source="modbus_tcp")
        )
    assert (await api.get(path)).json()["state"] == "ONLINE"
    assert (await api.get(f"/api/tags/{tag['id']}/value")).json()["source"] == "modbus_tcp"
    async with database_sessions() as session, session.begin():
        await upsert_current(session, tag["id"], quality="BAD", error="Malformed register response")
    assert (await api.get(path)).json()["state"] == "DEGRADED"
    assert (await api.get(f"/api/tags/{tag['id']}/value")).json()["value_numeric"] == 12
    await api.patch(f"/api/devices/{tag['device_id']}", json={"enabled": False})
    assert (await api.get(path)).json()["state"] == "DISABLED"


async def test_decoder_failure_becomes_bad_preserving_value(
    api: AsyncClient, database_sessions
) -> None:
    tag = await setup_tag(api)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(10), datetime.now(UTC), source="modbus_tcp")
        )
        config = (await polling.load_configuration(session))[0]
        await polling.collect_one(
            session,
            SimpleNamespace(read=AsyncMock(side_effect=DecodeError("Short register response"))),
            config,
        )
    value = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert value["quality"] == "BAD" and value["error"] == "Short register response"
    assert value["value_numeric"] == 10


async def test_scheduler_does_not_wait_for_independent_slow_bus(
    api: AsyncClient, database_sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    await setup_tag(api)
    slow = replace(base_tag(), id=1, transport=transport(id=1))
    fast = replace(base_tag(), id=2, transport=transport(id=2))
    disabled = replace(base_tag(), id=3, enabled=False, transport=transport(id=3))
    stop, entered = asyncio.Event(), asyncio.Event()
    calls = []

    async def collect(_session, _source, tag, acquired=None):
        calls.append(tag.id)
        if tag.id == 1:
            entered.set()
            await asyncio.sleep(60)
        else:
            await entered.wait()
            stop.set()

    monkeypatch.setattr(
        polling, "load_configuration", AsyncMock(return_value=[slow, fast, disabled])
    )
    monkeypatch.setattr(polling, "reconcile_disabled", AsyncMock())
    monkeypatch.setattr(polling, "collect_one", collect)
    source = SimpleNamespace(forget=Mock())
    await asyncio.wait_for(
        polling.poll_loop(
            SimpleNamespace(sessions=database_sessions),
            Settings(postgres_password="test"),
            stop,
            source,
        ),
        1,
    )
    assert calls == [1, 2]


async def test_serial_discovery_uses_host_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.worker.runtime.comports",
        lambda: [SimpleNamespace(device="detected", description="USB adapter")],
    )
    assert discover_ports() == [{"device": "detected", "description": "USB adapter"}]


async def test_source_switch_marks_history_boundary(api: AsyncClient, database_sessions) -> None:
    tag = await setup_tag(api, history_enabled=True)
    async with database_sessions() as session, session.begin():
        await upsert_current(
            session, tag["id"], reading=Reading(Decimal(1), datetime.now(UTC), source="simulator")
        )
        config = (await polling.load_configuration(session))[0]
        source = SimpleNamespace(
            read=AsyncMock(return_value=Reading(Decimal(2), datetime.now(UTC), source="modbus_tcp"))
        )
        await polling.collect_one(session, source, config)
    # The API range is upper-exclusive; coarse Windows clocks can equal the last insert.
    history = (
        await api.get(
            f"/api/tags/{tag['id']}/history",
            params={"to": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()},
        )
    ).json()["points"]
    assert [row["quality"] for row in history] == ["GOOD", "BAD", "GOOD"]
    assert [row["source"] for row in history] == ["simulator", None, "modbus_tcp"]
