"""Worker-only PyModbus transport adapter. No application API imports this module."""

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException, ModbusIOException

from app.core.config import Settings
from app.services.current_values import Reading
from app.worker.decoder import decode_registers, register_count
from app.worker.sources import CommunicationError, DecodeError, PollTag, Transport

logger = logging.getLogger(__name__)
READ_METHODS = {
    "coil": "read_coils",
    "discrete_input": "read_discrete_inputs",
    "input_register": "read_input_registers",
    "holding_register": "read_holding_registers",
}


def create_client(config: Transport) -> Any:
    common = {
        "timeout": config.timeout_ms / 1000,
        "retries": 0,
        "reconnect_delay": 0,
        "name": f"connection-{config.id}",
    }
    if config.protocol == "modbus_tcp":
        return AsyncModbusTcpClient(config.host, port=config.port, **common)
    return AsyncModbusSerialClient(
        config.serial_port,
        baudrate=config.baud_rate,
        parity=config.parity,
        stopbits=config.stop_bits,
        bytesize=config.data_bits,
        **common,
    )


def physical_port(port: str) -> str:
    # Resolves Linux by-id symlinks and normalizes Windows COM case/extended prefixes.
    return os.path.normcase(os.path.realpath(port.removeprefix("\\\\.\\")))


@dataclass
class ClientState:
    config: Transport
    client: Any = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state: str = "DISCONNECTED"
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    retry_at: float = 0
    failures: int = 0
    device_failures: dict[int, tuple[int, float]] = field(default_factory=dict)


class ConnectionManager:
    def __init__(
        self,
        settings: Settings,
        factory: Callable[[Transport], Any] = create_client,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings, self.factory, self.clock = settings, factory, clock
        self.entries: dict[int, ClientState] = {}
        self.conflicts: set[int] = set()

    def configure(self, connections: list[Transport]) -> None:
        wanted = {config.id: config for config in connections}
        for identifier, entry in list(self.entries.items()):
            if wanted.get(identifier) != entry.config:
                self.close_entry(entry)
                del self.entries[identifier]
        for identifier, config in wanted.items():
            if identifier not in self.entries:
                self.entries[identifier] = ClientState(
                    config, state="DISCONNECTED" if config.enabled else "DISABLED"
                )
        ports: dict[str, list[int]] = {}
        for config in connections:
            if config.enabled and config.protocol == "modbus_rtu":
                ports.setdefault(physical_port(config.serial_port), []).append(config.id)
        self.conflicts = {
            identifier for group in ports.values() if len(group) > 1 for identifier in group
        }
        for identifier in self.conflicts:
            entry = self.entries[identifier]
            self.close_entry(entry)
            entry.state, entry.last_error = (
                "ERROR",
                "Multiple enabled connections refer to the same physical serial port",
            )
            entry.last_error_at = datetime.now(UTC)

    def close_entry(self, entry: ClientState) -> None:
        if entry.client is not None:
            entry.client.close()
            entry.client = None
            logger.info("Modbus connection closed: connection_id=%s", entry.config.id)

    def close(self) -> None:
        for entry in self.entries.values():
            self.close_entry(entry)
            entry.state = "DISABLED" if not entry.config.enabled else "DISCONNECTED"

    def failed(self, entry: ClientState, message: str) -> None:
        self.close_entry(entry)
        entry.failures += 1
        delay = min(
            self.settings.modbus_backoff_max_seconds,
            self.settings.modbus_backoff_initial_seconds * 2 ** min(entry.failures - 1, 20),
        )
        entry.retry_at = self.clock() + delay
        entry.state, entry.last_error, entry.last_error_at = "ERROR", message, datetime.now(UTC)
        logger.warning(
            "Modbus communication failed: connection_id=%s error=%s retry_seconds=%s",
            entry.config.id,
            message,
            delay,
        )

    async def connected(self, entry: ClientState) -> None:
        if not entry.config.enabled:
            raise CommunicationError("Connection is disabled")
        if entry.config.id in self.conflicts:
            raise DecodeError(entry.last_error)
        if self.clock() < entry.retry_at:
            raise CommunicationError(f"Reconnect backoff: {entry.last_error}")
        if entry.client is not None and entry.client.connected:
            return
        entry.state = "CONNECTING"
        if entry.client is None:
            entry.client = self.factory(entry.config)
        logger.info(
            "Opening Modbus connection: connection_id=%s protocol=%s",
            entry.config.id,
            entry.config.protocol,
        )
        if not await entry.client.connect():
            raise OSError(
                "Unable to open transport (connection refused, unavailable host or serial port)"
            )
        entry.state = "CONNECTED"

    async def execute(
        self,
        config: Transport,
        operation: Callable[[Any], Any] | None = None,
        *,
        timeout_factor: int = 1,
        device_id: int | None = None,
    ) -> Any:
        entry = self.entries.get(config.id)
        if entry is None or entry.config != config:
            raise CommunicationError("Transport configuration changed; awaiting refresh")
        async with entry.lock:
            # Tests and reads share the same lock/client, including on RTU buses.
            try:
                _, retry_at = entry.device_failures.get(device_id, (0, 0))
                if device_id is not None and self.clock() < retry_at:
                    raise CommunicationError(f"Device {device_id} retry backoff")
                async with asyncio.timeout(config.timeout_ms / 1000 + 1):
                    await self.connected(entry)
                # Allow the library timeout to complete before the outer watchdog.
                async with asyncio.timeout(config.timeout_ms / 1000 * timeout_factor + 1):
                    result = await operation(entry.client) if operation else None
                if device_id is not None:
                    entry.device_failures.pop(device_id, None)
                if operation:
                    entry.last_success = datetime.now(UTC)
                entry.state, entry.last_error, entry.failures = "CONNECTED", None, 0
                return result
            except (CommunicationError, DecodeError):
                raise
            except asyncio.CancelledError:
                self.close_entry(entry)
                raise
            except (TimeoutError, OSError, ModbusException) as exc:
                if (
                    device_id is not None
                    and isinstance(exc, ModbusIOException)
                    and entry.client is not None
                    and entry.client.connected
                    and "No response received after" in str(exc)
                ):
                    failures = entry.device_failures.get(device_id, (0, 0))[0] + 1
                    delay = min(
                        self.settings.modbus_backoff_max_seconds,
                        self.settings.modbus_backoff_initial_seconds * 2 ** min(failures - 1, 20),
                    )
                    entry.device_failures[device_id] = (failures, self.clock() + delay)
                    logger.warning(
                        "Device timeout: connection_id=%s slave_id=%s retry_seconds=%s",
                        config.id, device_id, delay,
                    )
                    raise CommunicationError(f"Device {device_id}: timeout / no response") from exc
                message = (
                    "Modbus timeout / no response"
                    if isinstance(exc, TimeoutError)
                    else f"Modbus communication failure: {str(exc)[:300]}"
                )
                self.failed(entry, message)
                raise CommunicationError(message) from exc


class ModbusSource:
    def __init__(self, manager: ConnectionManager) -> None:
        self.manager = manager

    def forget(self, tag_id: int) -> None:
        pass  # No decoded-value cache; configuration is carried by each immutable PollTag.

    async def read(self, tag: PollTag) -> Reading:
        if tag.transport is None or tag.register_type not in READ_METHODS:
            raise DecodeError("Missing transport or unsupported register type")
        bit = tag.register_type in ("coil", "discrete_input")
        count = 1 if bit else register_count(tag.data_type)

        async def operation(client: Any) -> Any:
            return await getattr(client, READ_METHODS[tag.register_type])(
                tag.address, count=count, device_id=tag.slave_id
            )

        response = await self.manager.execute(tag.transport, operation, device_id=tag.slave_id)
        return self.decode_response(tag, response)

    @staticmethod
    def decode_response(tag: PollTag, response: Any) -> Reading:
        bit = tag.register_type in ("coil", "discrete_input")
        if response is None or not hasattr(response, "isError"):
            raise DecodeError("Invalid Modbus response")
        if response.isError():
            code = getattr(response, "exception_code", None)
            raise DecodeError(
                f"Modbus exception response (code {code}); verify slave and register map"
            )
        if bit:
            bits = getattr(response, "bits", None)
            if not bits or type(bits[0]) is not bool:
                raise DecodeError("Invalid bit response")
            value, raw = bits[0], str(bits[0]).lower()
        else:
            registers = getattr(response, "registers", None)
            if not isinstance(registers, list):
                raise DecodeError("Response has no register data")
            value, raw = decode_registers(
                registers, tag.data_type, tag.byte_order, tag.word_order, tag.scale, tag.offset
            )
        return Reading(value, datetime.now(UTC), raw, tag.transport.protocol)
