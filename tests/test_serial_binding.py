"""No physical USB access: enumeration and serial clients are injected."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_configuration import create
from test_modbus import FakeClient, transport
from test_runtime import worker
from test_telemetry import config as base_tag

from app.core.config import Settings
from app.models import ConnectionRuntime
from app.worker.modbus import ConnectionManager, physical_port
from app.worker.polling import transport_config
from app.worker.runtime import discover_ports
from app.worker.serial_binding import SerialBinder
from app.worker.serial_identity import match_adapter
from app.worker.sources import CommunicationError

pytestmark = pytest.mark.anyio


def config(**kw):
    values = dict(
        protocol="modbus_rtu",
        host=None,
        port=None,
        serial_port_mode="auto",
        usb_vid=123,
        usb_pid=456,
        baud_rate=9600,
        parity="N",
        data_bits=8,
        stop_bits=1,
    )
    return transport(**{**values, **kw})


def port(device="COM5", **kw):
    return {
        "device": device,
        "description": "Configured USB adapter",
        "vid": 123,
        "pid": 456,
        "serial_number": None,
        "hwid": "USB VID:PID=007B:01C8",
        **kw,
    }


def binder(sessions=None, factory=None, **settings):
    options = Settings(postgres_password="test", **settings)
    manager = ConnectionManager(options, factory or (lambda _: FakeClient()))
    return SerialBinder(SimpleNamespace(sessions=sessions), options, manager), manager


@pytest.mark.parametrize("name", ["COM7", "/dev/ttyUSB0", "/dev/ttyACM0"])
async def test_serial_identity_moves_ports(name):
    result = match_adapter(
        config(usb_serial_number="identity"),
        [port(name, serial_number="identity"), port("COM9", serial_number="other")],
    )
    assert result.status == "MATCHED_BY_SERIAL" and result.port == name


async def test_vid_pid_hardware_and_ambiguity():
    assert match_adapter(config(), [port()]).status == "MATCHED_BY_HARDWARE_ID"
    assert match_adapter(config(), [port(), port("COM7")]).status == "AMBIGUOUS"
    assert match_adapter(config(), [port(vid=99)]).status == "NOT_FOUND"
    assert match_adapter(config(usb_serial_number="missing"), [port()]).status == "NOT_FOUND"
    result = match_adapter(
        config(usb_hardware_id="location-B"),
        [port(hwid="location-A"), port("COM7", hwid="location-B")],
    )
    assert result.port == "COM7"
    result = match_adapter(
        config(usb_serial_number="cloned", usb_hardware_id="location-B"),
        [
            port(serial_number="cloned", hwid="location-A"),
            port("COM7", serial_number="cloned", hwid="location-B"),
        ],
    )
    assert result.status == "MATCHED_BY_HARDWARE_ID"


async def test_generic_hardware_id_does_not_disambiguate():
    result = match_adapter(config(usb_hardware_id="USB VID:PID=007B:01C8"), [port(), port("COM7")])
    assert result.status == "AMBIGUOUS" and result.port is None


async def test_discovery_metadata_and_zero_vid(monkeypatch):
    monkeypatch.setattr(
        "app.worker.runtime.comports",
        lambda: [SimpleNamespace(**port(vid=0), manufacturer="Maker", product="Adapter")],
    )
    result = discover_ports()[0]
    assert (
        result["vid"] == 0 and result["manufacturer"] == "Maker" and result["product"] == "Adapter"
    )


async def test_unplug_replug_reuses_config_and_reconnects():
    opened = []

    def factory(c):
        opened.append(c.serial_port)
        return FakeClient()

    resolver, manager = binder(factory=factory)
    c = config(usb_serial_number="identity")
    manager.configure([c])
    entry = manager.entries[c.id]
    with pytest.raises(CommunicationError):
        await manager.execute(c)
    await resolver.resolve(entry, [port(serial_number="identity")])
    await manager.execute(c)
    first = entry.client
    await resolver.resolve(entry, [])
    assert entry.resolved_port is None and entry.detection_status == "NOT_FOUND"
    first.close.assert_called_once()
    with pytest.raises(CommunicationError):
        await manager.execute(c)
    await resolver.resolve(entry, [port("COM8", serial_number="identity")])
    await manager.execute(c)
    assert (
        opened == ["COM5", "COM8"]
        and entry.config.serial_port is None
        and entry.config.version == c.version
    )
    manager.close()


async def test_manual_mode_unchanged():
    resolver, manager = binder()
    c = config(serial_port="COM3", serial_port_mode="manual", usb_vid=None, usb_pid=None)
    manager.configure([c])
    entry = manager.entries[c.id]
    await resolver.resolve(entry, [])
    await manager.execute(c)
    assert entry.resolved_port == "COM3" and entry.detection_status is None
    assert physical_port("com3") == physical_port(r"\\.\COM3")
    manager.close()


async def test_no_probe_without_eligible_tags():
    factory = Mock()
    resolver, manager = binder(factory=factory)
    c = config(serial_probe_enabled=True)
    manager.configure([c])
    await resolver.resolve(manager.entries[c.id], [port(), port("COM7")])
    assert "No enabled readable Tags" in manager.entries[c.id].detection_error
    factory.assert_not_called()


@pytest.mark.parametrize(
    "responders,expected",
    [({"COM5"}, "MATCHED_BY_MODBUS_PROBE"), ({"COM5", "COM7"}, "AMBIGUOUS"), (set(), "NOT_FOUND")],
)
async def test_probe_read_only_all_configured_slaves(responders, expected):
    reads = []
    clients = []

    def factory(c):
        client = FakeClient()
        clients.append(client)

        async def read(address, *, count, device_id):
            reads.append((c.serial_port, address, count, device_id, c.baud_rate))
            return SimpleNamespace(isError=lambda: c.serial_port not in responders, registers=[12])

        client.read_holding_registers = read
        client.write_register = Mock(side_effect=AssertionError("Detection must never write"))
        return client

    resolver, manager = binder(factory=factory)
    c = config(serial_probe_enabled=True)
    manager.configure([c])
    manager.probe_tags = [
        replace(
            base_tag(),
            transport=c,
            slave_id=slave,
            address=address,
            data_type="uint16",
            register_type="holding_register",
        )
        for slave, address in [(1, 10), (2, 20)]
    ]
    await resolver.resolve(manager.entries[c.id], [port(), port("COM7")])
    assert manager.entries[c.id].detection_status == expected
    assert all(r[1] in (10, 20) and r[3] in (1, 2) and r[4] == 9600 for r in reads)
    for client in clients:
        client.write_register.assert_not_called()
        client.close.assert_called_once()
    if expected == "MATCHED_BY_MODBUS_PROBE":
        assert manager.entries[c.id].resolved_port == "COM5"
        assert ("COM5", 20, 1, 2, 9600) in reads


async def test_probe_never_touches_reserved_manual_port():
    factory = Mock()
    resolver, manager = binder(factory=factory)
    c = config(serial_probe_enabled=True)
    manual = config(id=2, serial_port_mode="manual", serial_port="COM5", usb_vid=None, usb_pid=None)
    manager.configure([c, manual])
    manager.probe_tags = [replace(base_tag(), transport=c, slave_id=1)]
    await resolver.resolve(manager.entries[c.id], [port(), port("COM7")])
    assert manager.entries[c.id].detection_status == "AMBIGUOUS"
    factory.assert_not_called()


async def test_probe_budget_and_other_connection():
    async def slow():
        await asyncio.sleep(2)
        return True

    def factory(c):
        client = FakeClient()
        if c.protocol == "modbus_rtu":
            client.connect = AsyncMock(side_effect=slow)
        return client

    resolver, manager = binder(factory=factory, serial_probe_budget_seconds=1)
    c = config(serial_probe_enabled=True)
    tcp = transport(id=2)
    manager.configure([c, tcp])
    manager.probe_tags = [replace(base_tag(), transport=c, slave_id=1)]
    task = asyncio.create_task(resolver.resolve(manager.entries[c.id], [port(), port("COM7")]))
    await asyncio.wait_for(manager.execute(tcp), 0.2)
    await asyncio.wait_for(task, 1.5)
    assert (
        manager.entries[c.id].detection_status == "ERROR"
        and manager.entries[c.id].resolved_port is None
    )
    manager.close()


async def test_resolution_waits_for_bus_operation():
    resolver, manager = binder()
    c = config()
    manager.configure([c])
    entry = manager.entries[c.id]
    await resolver.resolve(entry, [port()])
    started = asyncio.Event()
    finish = asyncio.Event()

    async def operation(client):
        started.set()
        await finish.wait()
        assert client.connected

    task = asyncio.create_task(manager.execute(c, operation))
    await started.wait()
    rescan = asyncio.create_task(resolver.resolve(entry, [port("COM7")], True))
    await asyncio.sleep(0.01)
    assert not rescan.done()
    finish.set()
    await task
    await rescan
    assert entry.resolved_port == "COM7"
    manager.close()


async def auto_connection(api, **changes):
    return await create(
        api,
        "connections",
        **{
            "name": "Auto bus",
            "protocol": "modbus_rtu",
            "serial_port_mode": "auto",
            "usb_vid": 123,
            "usb_pid": 456,
            "baud_rate": 9600,
            "parity": "N",
            "stop_bits": 1,
            "data_bits": 8,
            **changes,
        },
    )


async def test_api_auto_crud_redetect_and_status(api, database_sessions, monkeypatch):
    row = await auto_connection(api)
    assert row["serial_port"] is None
    assert (await api.post(f"/api/connections/{row['id']}/redetect")).status_code == 503
    await worker(database_sessions)
    request = await api.post(f"/api/connections/{row['id']}/redetect")
    assert request.status_code == 202
    async with database_sessions() as session:
        from app.models import Connection

        c = transport_config(await session.get(Connection, row["id"]))
    resolver, manager = binder(database_sessions)
    manager.configure([c])
    monkeypatch.setattr("app.worker.serial_binding.discover_ports", lambda: [port()])
    await resolver.tick()
    assert manager.entries[c.id].resolved_port == "COM5"
    async with database_sessions() as session, session.begin():
        runtime = await session.get(ConnectionRuntime, c.id)
        assert runtime.redetect_completed_id == request.json()["request_id"]
        runtime.configuration_version = c.version
        runtime.updated_at = datetime.now(UTC)
        runtime.detected_port = "COM5"
        runtime.detection_status = "MATCHED_BY_HARDWARE_ID"
        runtime.detected_at = datetime.now(UTC)
    status = (await api.get(f"/api/connections/{c.id}/status")).json()
    assert status["detected_port"] == "COM5" and not status["redetect_pending"]
    assert (await api.get(f"/api/connections/{c.id}")).json()["serial_port"] is None
    assert (await api.post(f"/api/connections/{c.id}/test")).status_code == 202
    manager.close()


@pytest.mark.parametrize(
    "change",
    [
        {"usb_vid": None},
        {"usb_pid": 65536},
        {"serial_port": "COM3"},
        {"serial_port_mode": "wrong"},
        {"protocol": "modbus_tcp", "host": "localhost"},
    ],
)
async def test_invalid_auto_configuration(api, change):
    response = await api.post(
        "/api/connections",
        json={
            "name": "Invalid",
            "protocol": "modbus_rtu",
            "serial_port_mode": "auto",
            "usb_vid": 123,
            "usb_pid": 456,
            "baud_rate": 9600,
            "parity": "N",
            "stop_bits": 1,
            "data_bits": 8,
            **change,
        },
    )
    assert response.status_code == 422


async def test_enumeration_error_stops_old_binding():
    resolver, manager = binder()
    c = config()
    manager.configure([c])
    entry = manager.entries[c.id]
    await resolver.resolve(entry, [port()])
    await manager.execute(c)
    client = entry.client
    await resolver.resolve(entry, [], error="Enumeration failed")
    assert entry.resolved_port is None and entry.detection_status == "ERROR"
    client.close.assert_called_once()
    with pytest.raises(CommunicationError):
        await manager.execute(c)
    assert entry.state == "ERROR"


async def test_auto_cannot_claim_manual_alias():
    resolver, manager = binder()
    auto = config()
    manual = config(id=2, serial_port_mode="manual", serial_port="com5", usb_vid=None, usb_pid=None)
    manager.configure([manual, auto])
    await resolver.resolve(manager.entries[auto.id], [port("COM5")])
    assert manager.entries[auto.id].resolved_port is None
    assert manager.entries[auto.id].detection_status == "ERROR"
    await manager.execute(manual)
    manager.close()


async def test_redetect_forces_new_enumeration(database_sessions, monkeypatch, api):
    data = await auto_connection(api)
    await worker(database_sessions)
    from app.models import Connection

    async with database_sessions() as session:
        c = transport_config(await session.get(Connection, data["id"]))
    resolver, manager = binder(database_sessions)
    manager.configure([c])
    enumerate_ports = Mock(return_value=[port()])
    monkeypatch.setattr("app.worker.serial_binding.discover_ports", enumerate_ports)
    await resolver.tick()
    await manager.execute(c)
    old = manager.entries[c.id].client
    await resolver.tick()
    enumerate_ports.assert_called_once()
    await api.post(f"/api/connections/{c.id}/redetect")
    enumerate_ports.return_value = [port("COM9")]
    await resolver.tick()
    assert enumerate_ports.call_count == 2
    assert manager.entries[c.id].resolved_port == "COM9"
    old.close.assert_called_once()
    manager.close()
