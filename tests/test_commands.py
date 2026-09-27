import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from test_configuration import setup_tag
from test_modbus import PATTERNS
from test_runtime import worker

from app.core.config import Settings
from app.models import Command, Connection, Device, Tag, WorkerRuntime
from app.services.commands import COMMAND_CHANNEL
from app.services.current_values import Reading
from app.services.encoding import encode_registers, verification_matches
from app.services.live import LiveHub, NotificationListener
from app.worker.commands import CommandProcessor
from app.worker.decoder import decode_registers
from app.worker.modbus import ConnectionManager, ModbusSource
from app.worker.polling import load_configuration
from app.worker.simulator import SimulatorSource

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("dtype,words,raw", PATTERNS)
@pytest.mark.parametrize("byte", ["big", "little"])
@pytest.mark.parametrize("word", ["big", "little"])
@pytest.mark.parametrize("scale,offset", [("1", "0"), ("-0.1", "12")])
async def test_encoder_known_patterns_and_round_trip(dtype, words, raw, byte, word, scale, offset):
    value = Decimal(str(raw)) * Decimal(scale) + Decimal(offset)
    encoded = encode_registers(value, dtype, byte, word, Decimal(scale), Decimal(offset))
    expected = (
        [((item & 255) << 8) | (item >> 8) for item in words] if byte == "little" else words[:]
    )
    if word == "little":
        expected.reverse()
    assert encoded == expected
    assert verification_matches(
        value,
        decode_registers(encoded, dtype, byte, word, Decimal(scale), Decimal(offset))[0],
        dtype,
    )


@pytest.mark.parametrize(
    "value,dtype,scale",
    [
        ("1", "int16", "0"),
        ("1.5", "uint16", "1"),
        ("65536", "uint16", "1"),
        ("-32769", "int16", "1"),
        ("1e100", "float32", "1"),
        ("NaN", "float64", "1"),
    ],
)
async def test_encoder_rejects_unrepresentable_values(value, dtype, scale):
    with pytest.raises(ValueError):
        encode_registers(Decimal(value), dtype, "big", "big", Decimal(scale), Decimal(0))


async def prepare(api, sessions, mode="simulator", **overrides):
    await worker(sessions, mode=mode)
    async with sessions() as session, session.begin():
        await session.execute(update(WorkerRuntime).values(writes_enabled=True))
    return await setup_tag(api, **{"writable": True, **overrides})


async def enqueue(api, tag, value, **extra):
    response = await api.post(f"/api/tags/{tag['id']}/commands", json={"value": value, **extra})
    assert response.status_code == 202, response.text
    return response.json()


def processor(sessions, source=None, mode="simulator", **settings):
    return CommandProcessor(
        SimpleNamespace(sessions=sessions),
        Settings(
            postgres_password="test", telemetry_source=mode, command_retry_seconds=0.1, **settings
        ),
        source if source is not None else SimulatorSource(),
    )


@pytest.mark.parametrize("boolean", [True, False])
async def test_simulator_command_success_current_history_and_events(
    api, database_sessions, boolean
):
    tag = await prepare(
        api,
        database_sessions,
        history_enabled=True,
        **(
            {"register_type": "coil", "data_type": "bool"}
            if boolean
            else {"scale": 0.1, "offset": 2}
        ),
    )
    requested = True if boolean else "14.5"
    command = await enqueue(api, tag, requested)
    proc = processor(database_sessions)
    assert await proc.claim() == command["id"]
    assert await proc.claim() is None
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "SUCCESS", result
    assert (
        result["verified_value"] is True
        if boolean
        else Decimal(result["verified_value"]) == Decimal(requested)
    )
    assert result["attempt_count"] == 1
    current = (await api.get(f"/api/tags/{tag['id']}/value")).json()
    assert current["source"] == "simulator" and current["quality"] == "GOOD"
    assert current["value_boolean" if boolean else "value_numeric"] == (True if boolean else 14.5)
    async with database_sessions() as session:
        config = (await load_configuration(session))[0]
    assert (await proc.source.read(config)).value == (True if boolean else Decimal("14.5"))
    # First scheduler discovery must not discard a command applied before configuration refresh.
    proc.source.forget(config.id, config)
    assert (await proc.source.read(config)).value == (True if boolean else Decimal("14.5"))
    proc.source.forget(config.id, replace(config, address=config.address + 1))
    assert config.id not in proc.source.controls
    hub = LiveHub()
    queue = hub.subscribe()
    listener = NotificationListener(SimpleNamespace(sessions=database_sessions), hub, AsyncMock())
    listener.notified(None, 1, COMMAND_CHANNEL, str(command["id"]))
    await listener.dispatch()
    event = queue.get_nowait()
    assert event["type"] == "command_status" and event["data"]["status"] == "SUCCESS"
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409


@pytest.mark.parametrize(
    "changes,value",
    [
        ({"writable": False}, 1),
        ({"enabled": False}, 1),
        ({"register_type": "input_register", "writable": False}, 1),
        ({"register_type": "discrete_input", "data_type": "bool", "writable": False}, True),
        ({"min_value": 5}, 4),
        ({"max_value": 5}, 6),
        ({}, True),
        ({"register_type": "coil", "data_type": "bool"}, 1),
        ({"scale": 0}, 1),
    ],
)
async def test_api_rejects_invalid_writes(api, database_sessions, changes, value):
    tag = await prepare(api, database_sessions, **changes)
    assert (
        await api.post(f"/api/tags/{tag['id']}/commands", json={"value": value})
    ).status_code == 422


async def test_physical_switch_confirmation_and_worker_recheck(api, database_sessions):
    tag = await prepare(api, database_sessions, mode="modbus")
    async with database_sessions() as session, session.begin():
        await session.execute(update(WorkerRuntime).values(writes_enabled=False))
    assert (
        await api.post(
            f"/api/tags/{tag['id']}/commands", json={"value": 1, "confirm_physical": True}
        )
    ).status_code == 409
    async with database_sessions() as session, session.begin():
        await session.execute(update(WorkerRuntime).values(writes_enabled=True))
    assert (await api.post(f"/api/tags/{tag['id']}/commands", json={"value": 1})).status_code == 422
    command = await enqueue(api, tag, 1, confirm_physical=True)
    manager = ConnectionManager(
        Settings(postgres_password="test"),
        factory=lambda _: pytest.fail("Physical writes disabled: must not open a client"),
    )
    proc = processor(database_sessions, ModbusSource(manager), mode="modbus")
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "FAILED" and "disabled" in result["error_message"]


@pytest.mark.parametrize("entity", [Tag, Device, Connection])
async def test_configuration_disabled_after_queue(api, database_sessions, entity):
    tag = await prepare(api, database_sessions)
    command = await enqueue(api, tag, 1)
    async with database_sessions() as session, session.begin():
        await session.execute(update(entity).values(enabled=False))
    proc = processor(database_sessions)
    await proc.claim()
    await proc.process(command["id"])
    assert not proc.source.controls
    assert (await api.get(f"/api/commands/{command['id']}")).json()["status"] == "FAILED"


async def test_idempotency_cancel_filters_expiration_and_restart(api, database_sessions):
    tag = await prepare(api, database_sessions)
    token = str(uuid4())
    command = await enqueue(api, tag, 1, request_id=token)
    assert (await enqueue(api, tag, 1, request_id=token))["id"] == command["id"]
    assert (
        await api.post(f"/api/tags/{tag['id']}/commands", json={"value": 2, "request_id": token})
    ).status_code == 409
    assert (await api.post(f"/api/commands/{command['id']}/cancel")).json()["status"] == "CANCELLED"
    proc = processor(database_sessions)
    assert await proc.claim() is None
    old = await enqueue(api, tag, 2)
    async with database_sessions() as session, session.begin():
        await session.execute(
            update(Command)
            .where(Command.id == old["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert await proc.claim() is None
    assert (await api.get(f"/api/commands/{old['id']}")).json()["status"] == "EXPIRED"
    interrupted = await enqueue(api, tag, 3)
    await proc.claim()
    assert (await api.post(f"/api/commands/{interrupted['id']}/cancel")).status_code == 409
    await proc.recover()
    result = (await api.get(f"/api/commands/{interrupted['id']}")).json()
    assert result["status"] == "FAILED" and "Not replayed" in result["error_message"]
    response = await api.get(
        "/api/commands",
        params={"status": "FAILED", "device_id": tag["device_id"], "tag_id": tag["id"]},
    )
    assert [row["id"] for row in response.json()] == [interrupted["id"]]


async def test_mismatch_preserves_actual_and_is_not_retried(api, database_sessions):
    tag = await prepare(api, database_sessions)
    command = await enqueue(api, tag, 20)
    source = SimulatorSource()
    source.read = AsyncMock(
        return_value=Reading(Decimal(21), datetime.now(UTC), source="simulator")
    )
    proc = processor(database_sessions, source)
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "FAILED" and Decimal(result["verified_value"]) == 21
    assert "mismatch" in result["error_message"] and result["attempt_count"] == 1
    assert (await api.get(f"/api/tags/{tag['id']}/value")).json()["value_numeric"] == 21


class WriteClient:
    def __init__(self, fail_connect=0, fail_read=0):
        self.connected = False
        self.fail_connect, self.fail_read = fail_connect, fail_read
        self.writes = []
        self.words, self.bit = [0], False

    async def connect(self):
        if self.fail_connect:
            self.fail_connect -= 1
            raise OSError("Unavailable transport")
        self.connected = True
        return True

    def close(self):
        self.connected = False

    async def write_coil(self, address, value, *, device_id):
        self.writes.append((address, value, device_id))
        self.bit = value
        return SimpleNamespace(isError=lambda: False)

    async def write_register(self, address, value, *, device_id):
        return await self.write_registers(address, [value], device_id=device_id)

    async def write_registers(self, address, values, *, device_id):
        self.writes.append((address, values, device_id))
        self.words = values
        return SimpleNamespace(isError=lambda: False)

    async def read_holding_registers(self, address, *, count, device_id):
        if self.fail_read:
            self.fail_read -= 1
            raise OSError("Response lost after write")
        return SimpleNamespace(isError=lambda: False, registers=self.words)

    async def read_coils(self, address, *, count, device_id):
        return SimpleNamespace(isError=lambda: False, bits=[self.bit])


@pytest.mark.parametrize(
    "dtype,value",
    [("bool", True), ("uint16", "42"), ("float32", "12.5"), ("uint64", "12345678901234")],
)
async def test_physical_write_pipeline_with_mock_transport(api, database_sessions, dtype, value):
    tag = await prepare(
        api,
        database_sessions,
        mode="modbus",
        data_type=dtype,
        register_type="coil" if dtype == "bool" else "holding_register",
    )
    command = await enqueue(api, tag, value, confirm_physical=True)
    client = WriteClient()
    settings = Settings(
        postgres_password="test", modbus_writes_enabled=True, telemetry_source="modbus"
    )
    manager = ConnectionManager(settings, factory=lambda _: client)
    async with database_sessions() as session:
        config = (await load_configuration(session))[0]
    manager.configure([config.transport])
    proc = CommandProcessor(
        SimpleNamespace(sessions=database_sessions), settings, ModbusSource(manager)
    )
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "SUCCESS", result
    assert client.writes[0][0] == tag["address"] and client.writes[0][2] == 1
    manager.close()


@pytest.mark.parametrize("connect_fail,read_fail", [(1, 0), (0, 1), (0, 10)])
async def test_transient_retries_never_repeat_a_sent_write(
    api, database_sessions, connect_fail, read_fail
):
    tag = await prepare(api, database_sessions, mode="modbus")
    command = await enqueue(api, tag, 42, confirm_physical=True)
    client = WriteClient(connect_fail, read_fail)
    settings = Settings(
        postgres_password="test",
        telemetry_source="modbus",
        modbus_writes_enabled=True,
        command_retry_seconds=0.1,
        modbus_backoff_initial_seconds=0.1,
    )
    manager = ConnectionManager(settings, factory=lambda _: client)
    async with database_sessions() as session:
        manager.configure([(await load_configuration(session))[0].transport])
    proc = CommandProcessor(
        SimpleNamespace(sessions=database_sessions), settings, ModbusSource(manager)
    )
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == ("FAILED" if read_fail == 10 else "SUCCESS"), result
    assert len(client.writes) == 1
    assert result["attempt_count"] <= 3
    manager.close()


async def test_command_constraints(api, database_sessions):
    tag = await prepare(api, database_sessions)
    command = await enqueue(api, tag, 5)
    async with database_sessions() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(Command).where(Command.id == command["id"]).values(requested_boolean=True)
            )
        await session.rollback()
        assert await session.scalar(select(Command.id)) == command["id"]


async def test_configuration_retarget_and_source_switch_are_rejected(api, database_sessions):
    tag = await prepare(api, database_sessions)
    command = await enqueue(api, tag, 5)
    assert (await api.patch(f"/api/tags/{tag['id']}", json={"address": 15})).status_code == 200
    proc = processor(database_sessions)
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "FAILED" and "configuration changed" in result["error_message"]
    assert not proc.source.controls
    other = await enqueue(api, tag, 6)
    proc.settings.telemetry_source = "modbus"
    await proc.claim()
    await proc.process(other["id"])
    assert (await api.get(f"/api/commands/{other['id']}")).json()["status"] == "FAILED"
    assert not proc.source.controls


async def test_simulator_communication_failure_is_bounded(api, database_sessions):
    tag = await prepare(api, database_sessions)
    command = await enqueue(api, tag, 5)
    source = SimulatorSource(failure_probability=1)
    proc = processor(database_sessions, source)
    await proc.claim()
    await proc.process(command["id"])
    result = (await api.get(f"/api/commands/{command['id']}")).json()
    assert result["status"] == "FAILED" and result["attempt_count"] == 3
    assert not source.controls


async def test_float_tolerance_is_scaled_not_an_arbitrary_engineering_floor():
    assert verification_matches(Decimal("0.1"), Decimal("0.10000000149011612"), "float32")
    assert not verification_matches(Decimal("1e-20"), Decimal(0), "float32")
    assert not verification_matches(
        Decimal("1000000000001"),
        Decimal("1000000000002"),
        "float32",
        Decimal(1),
        Decimal("1000000000000"),
    )
    assert not verification_matches(Decimal(1), Decimal("1.01"), "float64")


@pytest.mark.parametrize("boolean", [True, False])
async def test_software_tcp_write_and_readback(api, database_sessions, boolean):
    from modbus_server_fixture import start_test_server

    server = await start_test_server()
    port = server.transport.sockets[0].getsockname()[1]
    manager = None
    try:
        tag = await prepare(
            api,
            database_sessions,
            mode="modbus",
            register_type="coil" if boolean else "holding_register",
            data_type="bool" if boolean else "float32",
            address=10 if boolean else 103,
        )
        device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
        assert (
            await api.patch(
                f"/api/connections/{device['connection_id']}",
                json={"host": "127.0.0.1", "port": port},
            )
        ).status_code == 200
        assert (
            await api.patch(f"/api/devices/{device['id']}", json={"slave_id": 7})
        ).status_code == 200
        command = await enqueue(api, tag, False if boolean else "-12.5", confirm_physical=True)
        settings = Settings(
            postgres_password="test", telemetry_source="modbus", modbus_writes_enabled=True
        )
        manager = ConnectionManager(settings)
        async with database_sessions() as session:
            config = (await load_configuration(session))[0]
        manager.configure([config.transport])
        source = ModbusSource(manager)
        proc = CommandProcessor(SimpleNamespace(sessions=database_sessions), settings, source)
        await proc.claim()
        await proc.process(command["id"])
        result = (await api.get(f"/api/commands/{command['id']}")).json()
        assert result["status"] == "SUCCESS", result
        reading = await source.read(config)
        assert reading.value == (False if boolean else Decimal("-12.5"))
    finally:
        if manager:
            manager.close()
        await server.shutdown()


async def test_rtu_lock_covers_write_and_readback_against_polling(api, database_sessions):
    tag = await prepare(api, database_sessions, mode="modbus")
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    response = await api.patch(
        f"/api/connections/{device['connection_id']}",
        json={
            "protocol": "modbus_rtu",
            "host": None,
            "port": None,
            "serial_port": "isolated-test-port",
            "baud_rate": 9600,
            "parity": "N",
            "stop_bits": 1,
            "data_bits": 8,
        },
    )
    assert response.status_code == 200, response.text
    command = await enqueue(api, tag, 42, confirm_physical=True)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class LockedClient(WriteClient):
        async def write_registers(self, address, values, *, device_id):
            calls.append("write_begin")
            entered.set()
            await release.wait()
            result = await super().write_registers(address, values, device_id=device_id)
            calls.append("write_end")
            return result

        async def read_holding_registers(self, address, *, count, device_id):
            calls.append("read")
            return await super().read_holding_registers(address, count=count, device_id=device_id)

    client = LockedClient()
    settings = Settings(
        postgres_password="test", telemetry_source="modbus", modbus_writes_enabled=True
    )
    manager = ConnectionManager(settings, factory=lambda _: client)
    async with database_sessions() as session:
        config = (await load_configuration(session))[0]
    manager.configure([config.transport])
    source = ModbusSource(manager)
    proc = CommandProcessor(SimpleNamespace(sessions=database_sessions), settings, source)
    await proc.claim()
    work = asyncio.create_task(proc.process(command["id"]))
    await asyncio.wait_for(entered.wait(), 1)
    poll = asyncio.create_task(source.read(config))
    try:
        await asyncio.sleep(0.03)
        assert calls == ["write_begin"] and not poll.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(work, poll), 2)
        assert calls == ["write_begin", "write_end", "read", "read"]
        assert (await api.get(f"/api/commands/{command['id']}")).json()["status"] == "SUCCESS"
    finally:
        release.set()
        work.cancel()
        poll.cancel()
        await asyncio.gather(work, poll, return_exceptions=True)
        manager.close()


async def test_lost_write_acknowledgement_verifies_without_resending(api, database_sessions):
    tag = await prepare(api, database_sessions, mode="modbus")
    command = await enqueue(api, tag, 42, confirm_physical=True)

    class LostAcknowledgement(WriteClient):
        async def write_registers(self, address, values, *, device_id):
            await super().write_registers(address, values, device_id=device_id)
            raise OSError("Write reached device but acknowledgement was lost")

    client = LostAcknowledgement()
    settings = Settings(
        postgres_password="test",
        telemetry_source="modbus",
        modbus_writes_enabled=True,
        # Keep retry beyond reconnect backoff; equal Windows timer deadlines can wake early.
        command_retry_seconds=0.2,
        modbus_backoff_initial_seconds=0.1,
    )
    manager = ConnectionManager(settings, factory=lambda _: client)
    async with database_sessions() as session:
        manager.configure([(await load_configuration(session))[0].transport])
    proc = CommandProcessor(
        SimpleNamespace(sessions=database_sessions), settings, ModbusSource(manager)
    )
    try:
        await proc.claim()
        await proc.process(command["id"])
        result = (await api.get(f"/api/commands/{command['id']}")).json()
        assert result["status"] == "SUCCESS" and result["attempt_count"] == 2
        assert len(client.writes) == 1
    finally:
        manager.close()
