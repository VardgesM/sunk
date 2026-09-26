from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class DashboardInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    is_default: bool = False


class DashboardRead(DashboardInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    revision: int
    created_at: datetime
    updated_at: datetime


class ValueConfig(StrictModel):
    decimals: int = Field(default=2, ge=0, le=10)
    show_unit: bool = True
    show_quality: bool = True
    show_last_update: bool = True


class GaugeConfig(StrictModel):
    min: float = 0
    max: float = 100
    decimals: int = Field(default=2, ge=0, le=10)
    unit: str | None = Field(default=None, max_length=40)
    warning_threshold: float | None = None
    critical_threshold: float | None = None

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.min >= self.max:
            raise ValueError("Gauge minimum must be less than maximum")
        for value in (self.warning_threshold, self.critical_threshold):
            if value is not None and not self.min <= value <= self.max:
                raise ValueError("Gauge thresholds must lie within the range")
        if (
            self.warning_threshold is not None
            and self.critical_threshold is not None
            and self.warning_threshold > self.critical_threshold
        ):
            raise ValueError("Warning threshold must not exceed critical threshold")
        return self


class ChartConfig(StrictModel):
    range_hours: int = Field(default=1, ge=1, le=8784)
    legend: bool = True
    refresh_seconds: int = Field(default=0, ge=0, le=86400)

    @model_validator(mode="after")
    def refresh(self) -> Self:
        if 0 < self.refresh_seconds < 30:
            raise ValueError("Chart refresh must be zero (manual) or at least 30 seconds")
        return self


class BooleanConfig(StrictModel):
    on_label: str = Field(default="ON", min_length=1, max_length=80)
    off_label: str = Field(default="OFF", min_length=1, max_length=80)


class ControlConfig(StrictModel):
    confirmation_required: bool = True


class AlarmConfig(StrictModel):
    severities: list[Literal["INFO", "WARNING", "CRITICAL"]] = Field(
        default_factory=lambda: ["INFO", "WARNING", "CRITICAL"], min_length=1, max_length=3
    )
    active_only: bool = True
    maximum_rows: int = Field(default=10, ge=1, le=100)


class TextConfig(StrictModel):
    text: str = Field(default="", max_length=4000)


CONFIGS = {
    "value": ValueConfig,
    "gauge": GaugeConfig,
    "chart": ChartConfig,
    "boolean": BooleanConfig,
    "switch": ControlConfig,
    "setpoint": ControlConfig,
    "alarms": AlarmConfig,
    "text": TextConfig,
}


class LayoutInput(StrictModel):
    breakpoint: Literal["lg", "md", "sm"]
    x: int = Field(ge=0, le=11)
    y: int = Field(ge=0, le=10000)
    w: int = Field(ge=1, le=12)
    h: int = Field(ge=2, le=40)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.x + self.w > {"lg": 12, "md": 6, "sm": 1}[self.breakpoint]:
            raise ValueError("Layout exceeds breakpoint columns")
        return self


class WidgetInput(StrictModel):
    type: Literal["value", "gauge", "chart", "boolean", "switch", "setpoint", "alarms", "text"]
    title: str = Field(min_length=1, max_length=200)
    configuration: dict = Field(default_factory=dict)
    tag_ids: list[Annotated[int, Field(gt=0, le=2147483647)]] = Field(
        default_factory=list, max_length=8
    )
    layouts: list[LayoutInput] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_widget(self) -> Self:
        self.configuration = CONFIGS[self.type].model_validate(self.configuration).model_dump()
        if len(set(self.tag_ids)) != len(self.tag_ids):
            raise ValueError("Tag bindings must be unique")
        count = len(self.tag_ids)
        if self.type in ("alarms", "text") and count != 0:
            raise ValueError("This widget has no Tag bindings")
        if self.type == "chart" and count < 1:
            raise ValueError("Chart requires at least one Tag")
        if self.type not in ("alarms", "text", "chart") and count != 1:
            raise ValueError("This widget requires exactly one Tag")
        if {item.breakpoint for item in self.layouts} != {"lg", "md", "sm"}:
            raise ValueError("Provide one layout for each breakpoint")
        return self


class WidgetRead(BaseModel):
    id: int
    dashboard_id: int
    type: str
    title: str
    configuration: dict
    tag_ids: list[int]
    layouts: list[LayoutInput]
    created_at: datetime
    updated_at: datetime


class DashboardDetail(DashboardRead):
    widgets: list[WidgetRead]


class LayoutItem(LayoutInput):
    widget_id: int = Field(gt=0)


class LayoutSave(StrictModel):
    revision: int = Field(gt=0)
    layouts: list[LayoutItem] = Field(max_length=300)
