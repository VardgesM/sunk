from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.services.current_values import Reading


@dataclass(frozen=True)
class Transport:
    id: int
    protocol: str
    enabled: bool
    version: datetime
    timeout_ms: int
    serial_port: str | None = None
    baud_rate: int | None = None
    parity: str | None = None
    stop_bits: float | None = None
    data_bits: int | None = None
    host: str | None = None
    port: int | None = None
    serial_port_mode: str = "manual"
    usb_vid: int | None = None
    usb_pid: int | None = None
    usb_serial_number: str | None = None
    usb_hardware_id: str | None = None
    usb_manufacturer: str | None = None
    usb_product: str | None = None
    serial_probe_enabled: bool = False


@dataclass(frozen=True)
class PollTag:
    id: int
    data_type: str
    poll_interval_ms: int
    scale: Decimal
    offset: Decimal
    min_value: Decimal | None
    max_value: Decimal | None
    enabled: bool
    tag_version: datetime
    device_version: datetime
    connection_version: datetime
    history_enabled: bool = False
    history_mode: str = "every_sample"
    history_interval_ms: int | None = None
    history_change_threshold: float | None = None
    transport: Transport | None = None
    device_id: int = 0
    slave_id: int = 0
    register_type: str = "holding_register"
    address: int = 0
    byte_order: str = "big"
    word_order: str = "big"


class DecodeError(ValueError):
    """Valid communication but an invalid response/encoding."""


class CommunicationError(Exception):
    """Source failed to acquire a reading; retain the previous successful value."""


class TelemetrySource(Protocol):
    async def read(self, tag: PollTag) -> Reading: ...

    def forget(self, tag_id: int) -> None: ...
