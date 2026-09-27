from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.telemetry import utc

CommandStatus = Literal[
    "QUEUED", "EXECUTING", "VERIFYING", "SUCCESS", "FAILED", "CANCELLED", "EXPIRED"
]


class CommandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: bool | Decimal
    request_id: UUID = Field(default_factory=uuid4)
    confirm_physical: bool = False

    @field_validator("value", mode="before")
    @classmethod
    def typed_value(cls, value: object) -> bool | Decimal:
        if type(value) is bool:
            return value
        if not isinstance(value, (int, float, str, Decimal)):
            raise ValueError("Provide a boolean or finite numeric value")
        try:
            number = Decimal(str(value))
        except Exception as exc:
            raise ValueError("Provide a boolean or finite numeric value") from exc
        if not number.is_finite() or abs(number) > Decimal("1.7976931348623157e308"):
            raise ValueError("Numeric value must be finite and within supported range")
        return number


class CommandRead(BaseModel):
    requested_by: int | None = None
    requested_by_username: str | None = None
    id: int
    request_id: str
    tag_id: int
    tag_name: str
    device_id: int
    device_name: str
    requested_value: Decimal | bool
    previous_value: Decimal | bool | None
    verified_value: Decimal | bool | None
    status: CommandStatus
    source: Literal["manual", "automation", "system"]
    telemetry_mode: Literal["simulator", "modbus"]
    attempt_count: int
    revision: int
    created_at: datetime
    expires_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None

    @field_serializer("created_at", "expires_at", "started_at", "completed_at")
    def timestamp(self, value: datetime | None) -> str | None:
        return utc(value).isoformat() if value else None
