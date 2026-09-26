from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Value = bool | Decimal


class TypedValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Value

    @field_validator("value", mode="before")
    @classmethod
    def typed(cls, value):
        if type(value) is bool:
            return value
        if not isinstance(value, (str, int, float, Decimal)):
            raise ValueError("Expected boolean or finite number")
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise ValueError("Expected boolean or finite number") from exc
        if not result.is_finite() or abs(result) > Decimal("1.7976931348623157e308"):
            raise ValueError("Number must be finite and within supported range")
        return result


class ConditionInput(TypedValue):
    tag_id: int = Field(gt=0, le=2147483647)
    operator: Literal[">", ">=", "<", "<=", "==", "!="]
    hysteresis: Decimal = Field(default=Decimal(0), ge=0, le=Decimal("1e308"), allow_inf_nan=False)
    sort_order: int = Field(default=0, ge=0, le=2147483647)

    @model_validator(mode="after")
    def valid(self):
        if type(self.value) is bool and self.operator not in ("==", "!="):
            raise ValueError("Boolean conditions require == or !=")
        if self.hysteresis and (type(self.value) is bool or self.operator in ("==", "!=")):
            raise ValueError("Hysteresis requires a numeric threshold operator")
        return self


class ActionInput(TypedValue):
    target_tag_id: int = Field(gt=0, le=2147483647)
    kind: Literal["SET_TAG_VALUE"] = "SET_TAG_VALUE"
    sort_order: int = Field(default=0, ge=0, le=2147483647)


class RuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    enabled: bool = False
    priority: int = Field(default=0, ge=-2147483648, le=2147483647)
    condition_mode: Literal["ALL", "ANY"] = "ALL"
    for_duration_ms: int | None = Field(default=None, ge=0, le=2147483647)
    cooldown_ms: int | None = Field(default=None, ge=0, le=2147483647)
    conditions: Annotated[list[ConditionInput], Field(min_length=1, max_length=100)]
    actions: Annotated[list[ActionInput], Field(min_length=1, max_length=100)]

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()

    @model_validator(mode="after")
    def unique_targets(self):
        if len({a.target_tag_id for a in self.actions}) != len(self.actions):
            raise ValueError("A rule may target each Tag only once")
        return self


class RuntimeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    state: str
    condition_state: bool
    true_since: datetime | None
    last_triggered_at: datetime | None
    cooldown_until: datetime | None
    last_result: str | None
    error: str | None


class RuleRead(RuleInput):
    id: int
    created_at: datetime
    updated_at: datetime
    runtime: RuntimeRead | None = None


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    triggered_at: datetime
    completed_at: datetime | None
    snapshot: list[dict]
    result: str
    error: str | None
    command_ids: list[int]
