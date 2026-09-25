from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field, field_serializer

from app.schemas.telemetry import Quality, utc


class HistoryPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    recorded_at: datetime
    source_timestamp: datetime | None = None
    value_numeric: Decimal | None = None
    value_boolean: bool | None = None
    value_text: str | None = None
    quality: Quality
    source: str | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    average: Decimal | None = None
    first_timestamp: datetime
    last_timestamp: datetime
    sample_count: int = 1
    has_invalid: bool = False

    @field_serializer("value_numeric", "minimum", "maximum", "average")
    def number(self, value: Decimal | None) -> int | float | None:
        if value is None:
            return None
        return int(value) if value == value.to_integral_value() else float(value)

    @computed_field
    @property
    def value_numeric_exact(self) -> str | None:
        return str(self.value_numeric) if self.value_numeric is not None else None

    @field_serializer("recorded_at", "source_timestamp", "first_timestamp", "last_timestamp")
    def timestamp(self, value: datetime | None) -> str | None:
        return utc(value).isoformat() if value else None


class HistoryTag(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    name: str
    unit: str | None
    data_type: str


class HistoryResponse(BaseModel):
    tag: HistoryTag
    from_timestamp: datetime
    to_timestamp: datetime
    count: int
    total_count: int
    downsampled: bool
    truncated: bool
    points: list[HistoryPoint]
