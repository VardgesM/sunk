"""Per-request RTU quiet time, including command write/read-back pairs."""

import asyncio
import time
from typing import Any

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.pdu import ModbusPDU


def quiet_seconds(baudrate: int, bytesize: int, parity: str, stopbits: float,
                  minimum_ms: float) -> float:
    """Modbus Serial Line V1.02 t3.5, plus an operator-configured USB/device margin."""
    bits = 1 + bytesize + (parity != "N") + stopbits
    protocol_minimum = 3.5 * bits / baudrate if baudrate <= 19200 else 0.00175
    return max(protocol_minimum, minimum_ms / 1000)


class PacedSerialClient(AsyncModbusSerialClient):
    """Keep PyModbus framing/retries intact; delay before each new RTU request.

    execute is the dispatch point used by all mixin read/write methods in pinned
    PyModbus 3.13.1. Never retry here: a timed-out write has an uncertain outcome.
    The outer physical-port lock still covers complete write/read-back operations.
    """

    def __init__(self, port: str, *, minimum_gap_ms: float, **kwargs: Any) -> None:
        super().__init__(port, **kwargs)
        self.quiet_seconds = quiet_seconds(
            kwargs["baudrate"], kwargs["bytesize"], kwargs["parity"],
            kwargs["stopbits"], minimum_gap_ms,
        )
        self._request_lock = asyncio.Lock()
        self._clock = time.monotonic
        self._sleep = asyncio.sleep
        self._finished_at: float | None = None

    async def execute(self, no_response_expected: bool, request: ModbusPDU) -> ModbusPDU:
        async with self._request_lock:
            # Also observe a quiet period on the first request after opening.
            remaining = self.quiet_seconds if self._finished_at is None else (
                self._finished_at + self.quiet_seconds - self._clock()
            )
            if remaining > 0:
                await self._sleep(remaining)
            try:
                return await super().execute(no_response_expected, request)
            finally:
                # Include errors/cancellation; never immediately follow an uncertain response.
                self._finished_at = self._clock()
