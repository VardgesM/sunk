from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, field_validator

from app.schemas.backup import FileDigest, Strict


def semver(value: str) -> tuple[int, int, int]:
    import re

    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Use a stable semantic version: major.minor.patch")
    return tuple(int(part) for part in value.split("."))


class ReleaseManifest(Strict):
    format: Literal["modbus-monitor-release"]
    format_version: Literal[1]
    version: str = Field(max_length=40)
    minimum_version: str = Field(max_length=40)
    created_at: AwareDatetime
    migration_revision: str = Field(pattern=r"^[a-zA-Z0-9_]{1,100}$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(gt=0, le=512 * 1024**2)
    files: dict[str, FileDigest] = Field(min_length=1, max_length=20000)

    @field_validator("version", "minimum_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        semver(value)
        return value


class Release(Strict):
    version: str
    tag: str
    published_at: AwareDatetime
    notes: str = Field(max_length=100000)
    manifest: ReleaseManifest


State = Literal[
    "IDLE",
    "CHECKING",
    "AVAILABLE",
    "DOWNLOADING",
    "VALIDATING",
    "BACKING_UP",
    "READY",
    "INSTALLING",
    "MIGRATING",
    "RESTARTING",
    "VERIFYING",
    "SUCCESS",
    "FAILED",
    "ROLLING_BACK",
    "ROLLED_BACK",
]
ACTIVE = {
    "CHECKING",
    "DOWNLOADING",
    "VALIDATING",
    "BACKING_UP",
    "READY",
    "INSTALLING",
    "MIGRATING",
    "RESTARTING",
    "VERIFYING",
    "ROLLING_BACK",
}


class UpdateStatus(Strict):
    state: State = "IDLE"
    installed_version: str
    channel: Literal["Stable"] = "Stable"
    last_checked: datetime | None = None
    release: Release | None = None
    available: bool = False
    runner_available: bool = False
    install_supported: bool = False
    message: str | None = None
    job_id: UUID | None = None
    requested_by: int | None = None
    from_version: str | None = None
    updated_at: datetime | None = None
    backup_id: UUID | None = None
    backup_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    previous_revision: str | None = None
    failure_stage: str | None = None
    error: str | None = None
    recovery_required: bool = False
    services_stopped: bool = False
    migration_started: bool = False


class InstallRequest(Strict):
    version: str = Field(max_length=40)
    confirmation: Literal["UPDATE"]
    passphrase: SecretStr = Field(min_length=12, max_length=1024)
