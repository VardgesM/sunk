from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

from app.core.version import APP_VERSION as APP_VERSION


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BackupPassword(Strict):
    passphrase: SecretStr = Field(min_length=12, max_length=1024)


class ConfirmRestore(Strict):
    confirmation: Literal["RESTORE"]


class FileDigest(Strict):
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Manifest(Strict):
    format: Literal["modbus-monitor-backup"] = "modbus-monitor-backup"
    format_version: Literal[1] = 1
    created_at: AwareDatetime
    application_version: str = Field(max_length=50)
    migration_revision: str = Field(max_length=100)
    deployment_mode: Literal["standalone", "edge", "cloud"]
    postgres_major: int = Field(ge=17, le=100)
    files: dict[str, FileDigest]


class BackupInfo(Strict):
    id: UUID
    kind: Literal["backup", "upload"]
    created_at: datetime
    size: int
    status: Literal[
        "CREATING",
        "AVAILABLE",
        "UPLOADED",
        "VALIDATED",
        "READY_OFFLINE",
        "RESTORING",
        "SUCCESS",
        "FAILED",
    ]
    manifest: Manifest | None = None
    error: str | None = None


class PortableObject(Strict):
    id: UUID
    values: dict


class ConfigurationData(Strict):
    locations: list[PortableObject] = Field(default_factory=list, max_length=10000)
    connections: list[PortableObject] = Field(default_factory=list, max_length=10000)
    devices: list[PortableObject] = Field(default_factory=list, max_length=10000)
    tags: list[PortableObject] = Field(default_factory=list, max_length=10000)
    dashboards: list[PortableObject] = Field(default_factory=list, max_length=1000)
    widgets: list[PortableObject] = Field(default_factory=list, max_length=10000)
    automation_rules: list[PortableObject] = Field(default_factory=list, max_length=1000)
    alarm_rules: list[PortableObject] = Field(default_factory=list, max_length=1000)


class ConfigurationDocument(Strict):
    format: Literal["modbus-monitor-config"] = "modbus-monitor-config"
    version: Literal[1] = 1
    exported_at: AwareDatetime
    application_version: str = Field(max_length=50)
    data: ConfigurationData


class ImportRequest(Strict):
    document: ConfigurationDocument
    confirmation: Literal["IMPORT"]
