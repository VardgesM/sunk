import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusIOException
from test_modbus import transport

from app.core.config import Settings
from app.worker.modbus import ConnectionManager
from app.worker.rtu_timing import PacedSerialClient, quiet_seconds


@pytest.mark.parametrize('baud,bits,parity,stop,minimum,expected', [
    (9600, 8, 'N', 1, 0, 35 / 9600),
    (9600, 8, 'E', 1, 0, 38.5 / 9600),
    (1200, 8, 'N', 2, 20, 38.5 / 1200),
    (19200, 8, 'E', 1, 0, 38.5 / 19200),
    (38400, 8, 'N', 1, 0, .00175),
    (9600, 8, 'N', 1, 20, .020),
])
def test_protocol_and_operator_minimum(baud, bits, parity, stop, minimum, expected):
    assert quiet_seconds(baud, bits, parity, stop, minimum) == pytest.approx(expected)


def client():
    return PacedSerialClient('unused-test-port', baudrate=9600, bytesize=8,
                             parity='N', stopbits=1, minimum_gap_ms=20, retries=0)


@pytest.mark.anyio
async def test_read_write_readback_all_use_gap_without_retry(monkeypatch):
    now = [0.0]
    calls = []
    async def execute(_self, no_response, pdu):
        calls.append((now[0], pdu.function_code))
        now[0] += .01
        return object()
    async def sleep(delay):
        now[0] += delay
    monkeypatch.setattr(AsyncModbusSerialClient, 'execute', execute)
    c = client()
    c._clock, c._sleep = lambda: now[0], sleep
    await c.read_input_registers(1, count=2, device_id=1)
    await c.write_coil(0, True, device_id=4)
    await c.read_coils(0, count=1, device_id=4)
    assert [fc for _, fc in calls] == [4, 5, 1]
    assert [t for t, _ in calls] == pytest.approx([.02, .05, .08])
    now[0] += 1
    await c.read_coils(0, count=1, device_id=4)
    assert calls[-1][0] == pytest.approx(1.09)  # no extra sleep after sufficient idle


@pytest.mark.anyio
async def test_timeout_is_not_retried_and_next_request_waits(monkeypatch):
    now = [0.0]
    async def sleep(delay):
        now[0] += delay
    execute = AsyncMock(side_effect=[ModbusIOException('timeout'), object()])
    monkeypatch.setattr(AsyncModbusSerialClient, 'execute', execute)
    c = client()
    c._clock, c._sleep = lambda: now[0], sleep
    with pytest.raises(ModbusIOException):
        await c.write_coil(0, True, device_id=4)
    assert execute.await_count == 1
    await c.read_coils(0, count=1, device_id=4)
    assert execute.await_count == 2
    assert now[0] == pytest.approx(.04)


@pytest.mark.anyio
async def test_cancel_while_waiting_does_not_transmit(monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(AsyncModbusSerialClient, 'execute', execute)
    c = client()
    c._sleep = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await c.write_coil(0, True, device_id=4)
    execute.assert_not_called()


@pytest.mark.anyio
async def test_serializes_requests_but_independent_clients_can_progress(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def execute(self, no_response, pdu):
        seen.append((self, pdu.dev_id))
        if pdu.dev_id == 1:
            entered.set()
            await release.wait()
        return object()
    monkeypatch.setattr(AsyncModbusSerialClient, 'execute', execute)
    a, b = client(), client()
    a._sleep = b._sleep = AsyncMock()
    first = asyncio.create_task(a.read_coils(0, device_id=1))
    await entered.wait()
    second = asyncio.create_task(a.read_coils(0, device_id=2))
    await b.read_coils(0, device_id=3)
    assert seen == [(a, 1), (b, 3)]
    release.set()
    await asyncio.gather(first, second)
    assert seen[-1] == (a, 2)


@pytest.mark.anyio
async def test_manager_factory_applies_setting_to_polls_and_probes():
    manager = ConnectionManager(Settings(postgres_password='test', modbus_rtu_min_gap_ms=50))
    config = transport(protocol='modbus_rtu', serial_port='unused-test-port',
                       baud_rate=9600, parity='N', stop_bits=1, data_bits=8)
    assert manager.factory(config).quiet_seconds == .05
    assert not isinstance(manager.factory(transport()), PacedSerialClient)


@pytest.mark.parametrize('gap', [-1, 251])
def test_gap_is_bounded(gap):
    with pytest.raises(ValidationError):
        Settings(postgres_password='test', modbus_rtu_min_gap_ms=gap)
