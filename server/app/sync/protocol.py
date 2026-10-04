from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.version import APP_VERSION
from app.sync.catalog import PRIORITIES


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    sequence: int = Field(gt=0)
    entity: str
    operation: Literal["upsert", "delete"]
    payload: dict

    @field_validator("entity")
    @classmethod
    def supported(cls, value):
        if value not in PRIORITIES:
            raise ValueError("Unsupported sync entity")
        return value


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    events: list[Event] = Field(max_length=500)


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    software_version: str = Field(default=APP_VERSION, max_length=50)


class RemoteAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    edge_id: UUID
    kind: Literal["command", "acknowledge"]
    target_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=64)
    expires_at: datetime
    payload: dict
