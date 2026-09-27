from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer

from app.schemas.telemetry import utc


class PortRead(BaseModel):
    device: str
    description: str
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    hwid: str | None = None
    manufacturer: str | None = None
    product: str | None = None


class SystemRuntime(BaseModel):
    application_mode: str = "standalone"
    mode: Literal["disabled", "simulator", "modbus", "unknown"]
    alive: bool
    writes_enabled: bool = False
    hostname: str | None = None
    heartbeat_at: datetime | None = None


class SerialPortsRead(BaseModel):
    worker_host: str
    observed_at: datetime
    ports: list[PortRead]
    error: str | None


class ConnectionStatus(BaseModel):
    detected_port: str | None = None
    detection_status: str | None = None
    detected_at: datetime | None = None
    detection_error: str | None = None
    redetect_pending: bool = False
    connection_id: int
    state: Literal["CONNECTED", "DISCONNECTED", "CONNECTING", "ERROR", "DISABLED"]
    last_success: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("last_success", "last_error_at", "updated_at", "detected_at")
    def timestamp(self, value: datetime | None) -> str | None:
        return utc(value).isoformat() if value else None


class ConnectionTest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    test_id: str | None
    state: Literal["NOT_REQUESTED", "PENDING", "SUCCEEDED", "FAILED", "EXPIRED"]
    success: bool | None = None
    message: str | None = None
    latency_ms: float | None = None


class DeviceStatus(BaseModel):
    device_id: int
    state: Literal["ONLINE", "OFFLINE", "DEGRADED", "DISABLED", "UNKNOWN"]
    last_success: datetime | None = None
