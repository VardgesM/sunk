from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

Role = Literal["ADMIN", "OPERATOR", "VIEWER"]


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=64)
    password: SecretStr = Field(max_length=1024)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordChange(PasswordInput):
    current_password: SecretStr = Field(max_length=1024)


class UserFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
    role: Role
    enabled: bool = True

    @field_validator("username")
    @classmethod
    def normalize(cls, value: str) -> str:
        return value.lower()


class UserCreate(UserFields, PasswordInput):
    pass


class UserRead(UserFields):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class Me(BaseModel):
    application_mode: str = "standalone"
    id: int
    username: str
    role: Role
    permissions: list[str]


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    timestamp: datetime
    user_id: int | None
    username: str | None
    action: str
    entity_type: str
    entity_id: int | None
    summary: str
