import re
from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Description = Annotated[str, StringConstraints(max_length=10000)]
PositiveID = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
PositiveInt = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Protocol = Literal["modbus_rtu", "modbus_tcp"]
RegisterType = Literal["coil", "discrete_input", "input_register", "holding_register"]
DataType = Literal[
    "bool", "uint16", "int16", "uint32", "int32", "float32", "uint64", "int64", "float64"
]
Order = Literal["big", "little"]
HistoryMode = Literal["every_sample", "fixed_interval", "on_change"]
Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$", max_length=64)]
Finite = Annotated[float, Field(allow_inf_nan=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, strict=True)


class LocationCreate(Input):
    name: Name
    parent_id: PositiveID | None = None
    description: Description | None = None
    sort_order: Annotated[int, Field(strict=True, ge=-2147483648, le=2147483647)] = 0


class LocationPatch(Input):
    name: Name | None = None
    parent_id: PositiveID | None = None
    description: Description | None = None
    sort_order: int | None = None


class ConnectionCreate(Input):
    serial_port_mode: Literal["manual", "auto"] = "manual"
    usb_vid: Annotated[int, Field(strict=True, ge=0, le=65535)] | None = None
    usb_pid: Annotated[int, Field(strict=True, ge=0, le=65535)] | None = None
    usb_serial_number: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    usb_hardware_id: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
        | None
    ) = None
    usb_manufacturer: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    usb_product: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    serial_probe_enabled: bool = False
    name: Name
    protocol: Protocol
    enabled: bool = True
    serial_port: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    baud_rate: PositiveInt | None = None
    parity: Literal["N", "E", "O"] | None = None
    stop_bits: Literal[1, 1.5, 2] | None = None
    data_bits: Literal[7, 8] | None = None
    host: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]
        | None
    ) = None
    port: Annotated[int, Field(strict=True, ge=1, le=65535)] | None = None
    timeout_ms: PositiveInt = 1000

    @model_validator(mode="after")
    def validate_transport(self) -> Self:
        identity = (
            self.usb_vid,
            self.usb_pid,
            self.usb_serial_number,
            self.usb_hardware_id,
            self.usb_manufacturer,
            self.usb_product,
        )
        if self.serial_port_mode == "manual" and (
            any(v is not None for v in identity) or self.serial_probe_enabled
        ):
            raise ValueError("Manual mode must not contain USB identity or probing settings")
        if self.serial_port_mode == "auto":
            if (
                self.protocol != "modbus_rtu"
                or self.serial_port is not None
                or self.usb_vid is None
                or self.usb_pid is None
            ):
                raise ValueError("Auto RTU requires USB VID/PID and no static serial_port")
        serial = (self.serial_port, self.baud_rate, self.parity, self.stop_bits, self.data_bits)
        if self.protocol == "modbus_rtu":
            if any(
                value is None
                for value in (serial if self.serial_port_mode == "manual" else serial[1:])
            ):
                raise ValueError(
                    "RTU requires serial_port, baud_rate, parity, stop_bits and data_bits"
                )
            if self.host is not None or self.port is not None:
                raise ValueError("RTU must not contain TCP host or port")
        else:
            if self.port is None and "port" not in self.model_fields_set:
                self.port = 502
            if self.host is None or self.port is None:
                raise ValueError("TCP requires host and port")
            if any(value is not None for value in serial):
                raise ValueError("TCP must not contain serial settings")
            try:
                ip_address(self.host)
            except ValueError:
                if not all(
                    re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                    for part in self.host.rstrip(".").split(".")
                ):
                    raise ValueError(
                        "Host must be an IP address or hostname, without scheme or port"
                    ) from None
        return self


class ConnectionPatch(Input):
    serial_port_mode: Literal["manual", "auto"] | None = None
    usb_vid: Annotated[int, Field(strict=True, ge=0, le=65535)] | None = None
    usb_pid: Annotated[int, Field(strict=True, ge=0, le=65535)] | None = None
    usb_serial_number: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    usb_hardware_id: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
        | None
    ) = None
    usb_manufacturer: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    usb_product: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
        | None
    ) = None
    serial_probe_enabled: bool | None = None
    name: Name | None = None
    protocol: Protocol | None = None
    enabled: bool | None = None
    serial_port: str | None = None
    baud_rate: int | None = None
    parity: str | None = None
    stop_bits: float | None = None
    data_bits: int | None = None
    host: str | None = None
    port: int | None = None
    timeout_ms: int | None = None


class DeviceCreate(Input):
    name: Name
    connection_id: PositiveID
    location_id: PositiveID | None = None
    slave_id: Annotated[int, Field(strict=True, ge=1, le=247)]
    enabled: bool = True
    description: Description | None = None


class DevicePatch(Input):
    name: Name | None = None
    connection_id: PositiveID | None = None
    location_id: PositiveID | None = None
    slave_id: int | None = None
    enabled: bool | None = None
    description: Description | None = None


class TagCreate(Input):
    name: Name
    key: Key
    device_id: PositiveID
    register_type: RegisterType
    address: Annotated[int, Field(strict=True, ge=0, le=65535)]
    data_type: DataType
    byte_order: Order = "big"
    word_order: Order = "big"
    scale: Finite = 1
    offset: Finite = 0
    unit: Annotated[str, StringConstraints(max_length=50)] | None = None
    poll_interval_ms: PositiveInt = 1000
    writable: bool = False
    history_enabled: bool = False
    history_mode: HistoryMode = "every_sample"
    history_interval_ms: PositiveInt | None = None
    history_change_threshold: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    history_retention_days: Annotated[int, Field(strict=True, gt=0, le=365000)] | None = None
    enabled: bool = True
    min_value: Finite | None = None
    max_value: Finite | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def validate_encoding(self) -> Self:
        if self.history_mode == "fixed_interval":
            if self.history_interval_ms is None or self.history_interval_ms < self.poll_interval_ms:
                raise ValueError("fixed_interval requires history_interval_ms >= poll_interval_ms")
        if (
            self.history_mode == "on_change"
            and self.data_type != "bool"
            and self.history_change_threshold is None
        ):
            raise ValueError("Numeric on_change requires a non-negative history_change_threshold")
        bit_object = self.register_type in ("coil", "discrete_input")
        if bit_object != (self.data_type == "bool"):
            raise ValueError(
                "Coils/discrete inputs require bool; registers require a numeric data type"
            )
        if self.writable and self.register_type not in ("coil", "holding_register"):
            raise ValueError("Only coils and holding registers may be writable")
        width = {"uint32": 2, "int32": 2, "float32": 2, "uint64": 4, "int64": 4, "float64": 4}.get(
            self.data_type, 1
        )
        if self.address + width > 65536:
            raise ValueError("The complete value must fit within zero-based addresses 0–65535")
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError("min_value must not exceed max_value")
        return self


class TagPatch(Input):
    name: Name | None = None
    key: Key | None = None
    device_id: PositiveID | None = None
    register_type: RegisterType | None = None
    address: int | None = None
    data_type: DataType | None = None
    byte_order: Order | None = None
    word_order: Order | None = None
    scale: Finite | None = None
    offset: Finite | None = None
    unit: str | None = None
    poll_interval_ms: int | None = None
    writable: bool | None = None
    history_enabled: bool | None = None
    history_mode: HistoryMode | None = None
    history_interval_ms: int | None = None
    history_change_threshold: Finite | None = None
    history_retention_days: int | None = None
    enabled: bool | None = None
    min_value: Finite | None = None
    max_value: Finite | None = None
    description: Description | None = None


class Record(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def utc_timestamp(self, value: datetime) -> str:
        # SQLite test databases lose timezone information; PostgreSQL uses timestamptz.
        return (
            value.replace(tzinfo=UTC).isoformat()
            if value.tzinfo is None
            else value.astimezone(UTC).isoformat()
        )


class LocationRead(LocationCreate, Record):
    pass


class ConnectionRead(ConnectionCreate, Record):
    pass


class DeviceRead(DeviceCreate, Record):
    connection_protocol: Protocol


class TagRead(TagCreate, Record):
    pass
