from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field, field_serializer

Quality = Literal["GOOD", "STALE", "BAD", "COMM_ERROR", "DISABLED"]


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class CurrentValueRead(BaseModel):
    tag_id: int
    key: str
    name: str
    device_id: int
    data_type: str
    unit: str | None
    enabled: bool
    effective_enabled: bool
    value_numeric: Decimal | None = None
    value_text: str | None = None
    value_boolean: bool | None = None
    raw_value: str | None = None
    quality: Quality | None = None
    source_timestamp: datetime | None = None
    updated_at: datetime | None = None
    error: str | None = None
    revision: int = 0
    source: Literal["simulator", "modbus_rtu", "modbus_tcp"] | None = None

    @field_serializer("value_numeric")
    def numeric_json(self, value: Decimal | None) -> int | float | None:
        if value is None:
            return None
        return int(value) if value == value.to_integral_value() else float(value)

    @computed_field
    @property
    def value_numeric_exact(self) -> str | None:
        # JSON numbers remain numeric; this companion protects 64-bit/decimal browser display.
        return str(self.value_numeric) if self.value_numeric is not None else None

    @field_serializer("source_timestamp", "updated_at")
    def timestamp_json(self, value: datetime | None) -> str | None:
        return utc(value).isoformat() if value else None


class TagValueEvent(BaseModel):
    type: Literal["tag_value"] = "tag_value"
    data: CurrentValueRead
