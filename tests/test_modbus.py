import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from modbus_server_fixture import start_test_server
from test_telemetry import config as base_tag

from app.core.config import Settings
from app.worker.decoder import decode_registers, register_count
from app.worker.modbus import ConnectionManager, ModbusSource, create_client
from app.worker.sources import CommunicationError, DecodeError, Transport


def transport(**changes) -> Transport:
    return replace(
        Transport(1, "modbus_tcp", True, datetime.now(UTC), 500, host="127.0.0.1", port=1),
        **changes,
    )


PATTERNS = [
    ("uint16", [0xFEDC], 65244),
    ("int16", [0xFFFE], -2),
    ("uint32", [0x1234, 0x5678], 305419896),
    ("int32", [0xFFFF, 0xFFFE], -2),
    ("float32", [0xC148, 0x0000], -12.5),
    ("uint64", [0xFEDC, 0xBA98, 0x7654, 0x3210], 18364758544493064720),
    ("int64", [0xFFFF, 0xFFFF, 0xFFFF, 0xFFFE], -2),
    ("float64", [0xC029, 0, 0, 0], -12.5),
]


@pytest.mark.parametrize("data_type,words,expected", PATTERNS)
@pytest.mark.parametrize("byte_order", ["big", "little"])
@pytest.mark.parametrize("word_order", ["big", "little"])
def test_known_decoder_patterns(
    data_type: str, words: list[int], expected: int | float, byte_order: str, word_order: str
) -> None:
    wire = list(words)
    if byte_order == "little":
        wire = [(word & 255) * 256 + (word >> 8) for word in wire]
    if word_order == "little":
        wire.reverse()
    value, raw = decode_registers(wire, data_type, byte_order, word_order, Decimal(1), Decimal(0))
    assert value == Decimal(str(expected))
    assert register_count(data_type) == len(words)
    assert "registers=" in raw


@pytest.mark.parametrize(
    "words,byte,word",
    [
        ([0x1234, 0x5678], "big", "big"),
        ([0x3412, 0x7856], "little", "big"),
        ([0x5678, 0x1234], "big", "little"),
        ([0x7856, 0x3412], "little", "little"),
    ],
)
def test_explicit_word_byte_matrix(words: list[int], byte: str, word: str) -> None:
    assert decode_registers(words, "uint32", byte, word, Decimal(1), Decimal(0))[0] == 305419896


@pytest.mark.parametrize(
    "scale,offset,expected", [(".1", "20", "19.8"), ("-2", "-3", "1"), ("0", "12", "12")]
)
def test_engineering_transform(scale: str, offset: str, expected: str) -> None:
    assert decode_registers([65534], "int16", "big", "big", Decimal(scale), Decimal(offset))[
        0
    ] == Decimal(expected)


@pytest.mark.parametrize(
    "words,dtype",
    [
        ([], "uint16"),
        ([1, 2], "uint16"),
        ([-1], "uint16"),
        ([65536], "uint16"),
        ([True], "uint16"),
        ([0x7FC0, 0], "float32"),
        ([0x7FF0, 0, 0, 0], "float64"),
        ([1], "bool"),
    ],
)
def test_invalid_decoding(words: list[int], dtype: str) -> None:
    with pytest.raises(DecodeError):
        decode_registers(words, dtype, "big", "big", Decimal(1), Decimal(0))


@pytest.mark.anyio
async def test_client_factory_uses_stored_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    tcp, serial = Mock(), Mock()
    monkeypatch.setattr("app.worker.modbus.AsyncModbusTcpClient", tcp)
    monkeypatch.setattr("app.worker.modbus.AsyncModbusSerialClient", serial)
    create_client(transport(host="configured.example", port=1502, timeout_ms=750))
    assert tcp.call_args.args == ("configured.example",)
    assert tcp.call_args.kwargs["port"] == 1502
    assert tcp.call_args.kwargs["timeout"] == 0.75
    assert tcp.call_args.kwargs["retries"] == 0
    assert tcp.call_args.kwargs["reconnect_delay"] == 0
    create_client(
        transport(
            protocol="modbus_rtu",
            serial_port="operator-port",
            baud_rate=38400,
            parity="E",
            stop_bits=1.5,
            data_bits=7,
            host=None,
            port=None,
        )
    )
    assert serial.call_args.args == ("operator-port",)
    assert {
        k: serial.call_args.kwargs[k] for k in ("baudrate", "parity", "stopbits", "bytesize")
    } == {"baudrate": 38400, "parity": "E", "stopbits": 1.5, "bytesize": 7}


class FakeClient:
    def __init__(self) -> None:
        self.connected = False
        self.connect = AsyncMock(side_effect=self.open)
        self.close = Mock(side_effect=self.shut)

    async def open(self) -> bool:
        self.connected = True
        return True

    def shut(self) -> None:
        self.connected = False


@pytest.mark.anyio
async def test_reuse_backoff_configuration_and_shutdown() -> None:
    clients: list[FakeClient] = []

    def factory(_config: Transport) -> FakeClient:
        client = FakeClient()
        clients.append(client)
        return client

    now = [0.0]
    manager = ConnectionManager(Settings(postgres_password="test"), factory, lambda: now[0])
    config = transport()
    manager.configure([config])
    await manager.execute(config)
    await manager.execute(config)
    assert len(clients) == 1 and clients[0].connect.await_count == 1
    with pytest.raises(CommunicationError):
        await manager.execute(config, AsyncMock(side_effect=TimeoutError()))
    assert manager.entries[1].state == "ERROR"
    with pytest.raises(CommunicationError, match="backoff"):
        await manager.execute(config)
    assert len(clients) == 1
    now[0] = 2
    await manager.execute(config)
    assert len(clients) == 2
    changed = replace(config, port=2502)
    manager.configure([changed])
    assert clients[-1].close.called
    with pytest.raises(CommunicationError, match="changed"):
        await manager.execute(config)
    await manager.execute(changed)
    manager.close()
    assert all(client.close.called for client in clients)


@pytest.mark.anyio
async def test_rtu_serialization_and_independent_connections() -> None:
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: FakeClient())
    first = transport(protocol="modbus_rtu", serial_port="bus-a")
    second = transport(id=2, protocol="modbus_rtu", serial_port="bus-b")
    manager.configure([first, second])
    active, maximum = 0, 0
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation(_client):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        entered.set()
        await release.wait()
        active -= 1

    a = asyncio.create_task(manager.execute(first, operation))
    await entered.wait()
    b = asyncio.create_task(manager.execute(first, operation))
    await asyncio.wait_for(manager.execute(second), 0.2)
    assert maximum == 1 and not b.done()
    release.set()
    await asyncio.gather(a, b)
    assert maximum == 1
    manager.close()


@pytest.mark.anyio
async def test_duplicate_rtu_bus_rejected_and_disabled_never_opened() -> None:
    factory = Mock(return_value=FakeClient())
    manager = ConnectionManager(Settings(postgres_password="test"), factory)
    first = transport(protocol="modbus_rtu", serial_port="same-bus")
    second = replace(first, id=2)
    manager.configure([first, second])
    with pytest.raises(DecodeError, match="same physical"):
        await manager.execute(first)
    manager.configure([replace(first, enabled=False)])
    with pytest.raises(CommunicationError, match="disabled"):
        await manager.execute(replace(first, enabled=False))
    factory.assert_not_called()


@pytest.mark.anyio
async def test_real_tcp_read_types_addressing_failure_and_restart() -> None:
    server = await start_test_server()
    port = server.transport.sockets[0].getsockname()[1]
    config = transport(port=port)
    now = [0.0]
    manager = ConnectionManager(Settings(postgres_password="test"), clock=lambda: now[0])
    manager.configure([config])
    source = ModbusSource(manager)
    base = replace(base_tag(), transport=config, slave_id=7)
    try:
        for register, address, dtype, expected in [
            ("holding_register", 100, "uint32", Decimal(305419896)),
            ("holding_register", 102, "int16", Decimal(-2)),
            ("holding_register", 103, "float32", Decimal(25)),
            ("input_register", 200, "uint16", Decimal(7)),
            ("coil", 10, "bool", True),
            ("discrete_input", 20, "bool", False),
        ]:
            reading = await source.read(
                replace(base, register_type=register, address=address, data_type=dtype)
            )
            assert reading.value == expected and reading.source == "modbus_tcp"
        reading = await source.read(
            replace(
                base, register_type="input_register", address=200, data_type="uint16", slave_id=11
            )
        )
        assert reading.value == 11
        with pytest.raises(DecodeError, match="exception response"):
            await source.read(replace(base, address=600, data_type="uint16"))
        await server.shutdown()
        await asyncio.sleep(0.05)
        with pytest.raises(CommunicationError):
            await source.read(replace(base, address=100, data_type="uint16"))
        server = await start_test_server(port=port)
        now[0] += 31
        assert (await source.read(replace(base, address=100, data_type="uint16"))).value == 0x1234
    finally:
        manager.close()
        await server.shutdown()


def test_modes_are_explicit_and_incompatible_settings_rejected() -> None:
    assert Settings(postgres_password="test", telemetry_source="modbus", simulator_enabled=False).source_mode == "modbus"
    assert Settings(postgres_password="test", simulator_enabled=True).source_mode == "simulator"
    with pytest.raises(ValueError, match="Disable SIMULATOR_ENABLED"):
        Settings(postgres_password="test", simulator_enabled=True, telemetry_source="modbus")


@pytest.mark.anyio
async def test_missing_slave_does_not_close_bus_or_block_other_slave() -> None:
    from pymodbus.exceptions import ModbusIOException

    client = FakeClient()
    now = [0.0]
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: client, lambda: now[0])
    config = transport(protocol="modbus_rtu", serial_port="test-bus")
    manager.configure([config])
    missing = AsyncMock(side_effect=ModbusIOException(
        "No response received after 0 retries, continue with next request"
    ))
    with pytest.raises(CommunicationError, match="Device 1: timeout"):
        await manager.execute(config, missing, device_id=1)
    client.close.assert_not_called()
    healthy = AsyncMock(return_value=42)
    assert await manager.execute(config, healthy, device_id=2) == 42
    with pytest.raises(CommunicationError, match="Device 1 retry backoff"):
        await manager.execute(config, missing, device_id=1)
    assert missing.await_count == 1
    now[0] = 2
    assert await manager.execute(config, healthy, device_id=1) == 42
    assert manager.entries[config.id].device_failures == {}
    manager.close()


@pytest.mark.anyio
async def test_connect_time_does_not_consume_response_timeout() -> None:
    client = FakeClient()
    original = client.open

    async def slow_connect():
        await asyncio.sleep(.03)
        return await original()

    client.connect = AsyncMock(side_effect=slow_connect)
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: client)
    config = transport(timeout_ms=40)
    manager.configure([config])

    async def response(_client):
        await asyncio.sleep(.03)
        return 123

    assert await manager.execute(config, response, device_id=1) == 123
    manager.close()


@pytest.mark.anyio
async def test_grouped_reads_decode_offsets_and_one_wire_request() -> None:
    from types import SimpleNamespace

    from app.worker.grouping import read_groups

    client = FakeClient()
    client.read_holding_registers = AsyncMock(return_value=SimpleNamespace(
        isError=lambda: False, registers=[12, 0xFFFF, 0xFFFE, 0x41C8, 0]
    ))
    config = transport()
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: client)
    manager.configure([config])
    base = replace(base_tag(), transport=config, slave_id=7, device_id=4,
                   data_type="uint16", address=100)
    tags = [base, replace(base, id=2, address=101, data_type="int32"),
            replace(base, id=3, address=103, data_type="float32")]
    assert read_groups(tags) == [tags]
    values = await ModbusSource(manager).read_many(tags)
    assert [values[t.id].value for t in tags] == [Decimal(12), Decimal(-2), Decimal(25)]
    assert len({values[t.id].source_timestamp for t in tags}) == 1
    client.read_holding_registers.assert_awaited_once_with(100, count=5, device_id=7)
    manager.close()


def test_group_boundaries_and_protocol_limits() -> None:
    from app.worker.grouping import read_groups

    base = replace(base_tag(), transport=transport(), data_type="uint16", address=0)
    contiguous = [replace(base, id=i+1, address=i) for i in range(126)]
    assert [len(g) for g in read_groups(contiguous)] == [125, 1]
    for changed in (
        replace(base, id=2, address=2),
        replace(base, id=2, address=1, device_id=99),
        replace(base, id=2, address=1, slave_id=99),
        replace(base, id=2, address=1, register_type="input_register"),
        replace(base, id=2, address=1, transport=transport(id=2)),
    ):
        assert len(read_groups([base, changed])) == 2
    bits = [replace(base, id=i+1, address=i, data_type="bool", register_type="coil")
            for i in range(2001)]
    assert [len(g) for g in read_groups(bits)] == [2000, 1]


@pytest.mark.anyio
async def test_grouped_bits_and_truncated_response() -> None:
    from types import SimpleNamespace

    client = FakeClient()
    client.read_coils = AsyncMock(return_value=SimpleNamespace(
        isError=lambda: False, bits=[True, False, True, False, False, False, False, False]
    ))
    config = transport()
    manager = ConnectionManager(Settings(postgres_password="test"), lambda _: client)
    manager.configure([config])
    base = replace(base_tag(), transport=config, data_type="bool", register_type="coil", address=0)
    tags = [replace(base, id=i+1, address=i) for i in range(3)]
    source = ModbusSource(manager)
    values = await source.read_many(tags)
    assert [values[t.id].value for t in tags] == [True, False, True]
    client.read_coils.return_value.bits = [True]
    values = await source.read_many(tags)
    assert all(isinstance(v, DecodeError) for v in values.values())
    manager.close()
