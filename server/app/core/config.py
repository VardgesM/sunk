from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "modbus_monitor"
    postgres_user: str = "modbus_monitor"
    postgres_password: SecretStr
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    worker_heartbeat_seconds: float = Field(default=10, ge=1, le=3600)
    telegram_timezone: str = "UTC"

    @field_validator("telegram_timezone")
    @classmethod
    def valid_telegram_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("TELEGRAM_TIMEZONE must be a valid IANA time zone") from None
        return value

    telegram_enabled: bool = False
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_timeout_seconds: float = Field(default=5, ge=1, le=15)
    modbus_writes_enabled: bool = False
    command_max_attempts: int = Field(default=3, ge=1, le=5)
    command_max_age_seconds: int = Field(default=60, ge=1, le=3600)
    command_retry_seconds: float = Field(default=1, ge=0.1, le=30)
    simulator_enabled: bool = False
    telemetry_source: Literal["disabled", "simulator", "modbus"] | None = None
    modbus_backoff_initial_seconds: float = Field(default=1, ge=0.1, le=60)
    modbus_backoff_max_seconds: float = Field(default=30, ge=1, le=300)
    serial_scan_seconds: float = Field(default=5, ge=1, le=300)
    serial_probe_budget_seconds: float = Field(default=10, ge=1, le=30)
    worker_max_parallel_connections: int = Field(default=32, ge=1, le=256)

    @field_validator("telemetry_source", mode="before")
    @classmethod
    def empty_source(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def validate_source(self) -> "Settings":
        if self.telemetry_source == "modbus" and self.simulator_enabled:
            raise ValueError("Disable SIMULATOR_ENABLED before selecting real Modbus")
        if self.modbus_backoff_max_seconds < self.modbus_backoff_initial_seconds:
            raise ValueError("Maximum backoff must be >= initial backoff")
        return self

    @property
    def source_mode(self) -> str:
        return self.telemetry_source or ("simulator" if self.simulator_enabled else "disabled")

    simulator_failure_probability: float = Field(default=0, ge=0, le=1)
    worker_config_refresh_seconds: float = Field(default=2, ge=0.1, le=3600)
    stale_multiplier: float = Field(default=3, ge=1, le=1000)
    stale_check_seconds: float = Field(default=1, ge=0.1, le=60)
    live_updates_enabled: bool = True
    history_cleanup_seconds: float = Field(default=3600, ge=1, le=86400)

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
