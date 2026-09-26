from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.automation import TypedValue


class AlarmInput(TypedValue):
    tag_id: int = Field(gt=0, le=2147483647)
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    hysteresis: Decimal = Field(default=Decimal(0), ge=0, le=Decimal("1e308"), allow_inf_nan=False)

    @model_validator(mode="after")
    def compatible(self):
        if type(self.value) is bool and self.operator not in ("==", "!="):
            raise ValueError("Boolean alarms require == or !=")
        if self.hysteresis and (type(self.value) is bool or self.operator in ("==", "!=")):
            raise ValueError("Hysteresis requires a numeric threshold operator")
        return self

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    severity: Literal["INFO", "WARNING", "CRITICAL"] = "WARNING"
    enabled: bool = False
    for_duration_ms: int | None = Field(default=None, ge=0, le=2147483647)
    notification_enabled: bool = False

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class AlarmRead(AlarmInput):
    id: int
    created_at: datetime
    updated_at: datetime


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    tag_id: int
    name: str
    tag_name: str
    unit: str | None
    condition: str
    severity: str
    state: str
    value_numeric: str | None
    value_boolean: bool | None
    activated_at: datetime
    acknowledged_at: datetime | None
    cleared_at: datetime | None
    clear_reason: str | None
    revision: int

    @field_validator("value_numeric", mode="before")
    @classmethod
    def numeric(cls, value):
        return str(value) if value is not None else None


class DestinationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: str = Field(min_length=1, max_length=100, pattern=r"^(-?[0-9]+|@[A-Za-z0-9_]+)$")


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    event_id: int | None
    kind: str
    status: str
    attempt_count: int
    created_at: datetime
    completed_at: datetime | None
    error: str | None
