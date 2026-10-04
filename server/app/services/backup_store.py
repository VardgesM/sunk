"""Filesystem artifacts with OS locks and UUID-only addressing; no backup credentials stored."""

import asyncio
import json
import os
import tarfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ParamSpec, TypeVar
from uuid import UUID, uuid4

from filelock import FileLock, Timeout
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.schemas.backup import APP_VERSION, BackupInfo, Manifest
from app.services.backup_archive import BackupError, digest_file, encrypt, unpack
from app.services.backup_postgres import check_revision, dump, validate_dump

P = ParamSpec("P")
T = TypeVar("T")


async def blocking(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    # A cancelled request must not release an artifact lock while its thread still writes.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class BackupStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.backup_directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, identifier: str | UUID, extension: str) -> Path:
        target = self.root / (str(UUID(str(identifier))) + extension)
        if target.is_symlink() or target.resolve().parent != self.root:
            raise BackupError("Unsafe artifact path")
        return target

    @contextmanager
    def lock(self, identifier: str | UUID | None = None) -> Iterator[None]:
        name = str(UUID(str(identifier))) if identifier else "operations"
        try:
            with FileLock(str(self.root / (name + ".lock")), timeout=0, thread_local=False):
                yield
        except Timeout:
            raise BackupError(
                "Backup is busy; retry after the current operation finishes"
            ) from None

    def write(self, info: BackupInfo) -> None:
        target = self.path(info.id, ".json")
        temporary = self.path(info.id, ".json.tmp")
        temporary.write_text(info.model_dump_json(), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(target)

    def read(self, identifier: str | UUID) -> BackupInfo:
        path = self.path(identifier, ".json")
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            raise BackupError("Backup not found")
        try:
            return BackupInfo.model_validate_json(path.read_bytes())
        except (ValidationError, OSError):
            raise BackupError("Backup metadata is unreadable") from None

    def listing(self) -> list[BackupInfo]:
        rows = []
        for path in self.root.glob("*.json"):
            try:
                UUID(path.stem)
            except ValueError:
                continue
            rows.append(self.read(path.stem))
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    def new(self, kind: str) -> BackupInfo:
        info = BackupInfo(
            id=uuid4(),
            kind=kind,
            created_at=datetime.now(UTC),
            size=0,
            status="CREATING" if kind == "backup" else "UPLOADED",
        )
        self.write(info)
        return info

    def delete(self, identifier: str | UUID) -> None:
        with self.lock(identifier):
            info = self.read(identifier)
            if info.status in ("CREATING", "READY_OFFLINE", "RESTORING"):
                raise BackupError(
                    "An active restore/backup cannot be deleted; cancel preparation first"
                )
            for extension in (".mmbak", ".json", ".json.tmp", ".settings.json"):
                self.path(identifier, extension).unlink(missing_ok=True)

    def retain(self) -> None:
        backups = [
            r
            for r in self.listing()
            if r.kind == "backup" and r.status in ("AVAILABLE", "VALIDATED", "SUCCESS")
        ]
        for info in backups[self.settings.backup_retention_count :]:
            try:
                self.delete(info.id)
            except BackupError:
                # A download/restore has a file lock. Retention retries on the next creation.
                continue

    def create(
        self, info: BackupInfo, password: str, revision: str, major: int, snapshot: str
    ) -> BackupInfo:
        with TemporaryDirectory(prefix="backup-", dir=self.root) as directory:
            work = Path(directory)
            database = work / "database.dump"
            dump(self.settings, database, snapshot)
            settings = {
                k: v
                for k, v in self.settings.model_dump(mode="json").items()
                if not isinstance(getattr(self.settings, k), SecretStr)
            }
            # Runtime paths/credentials are reconfigured on a replacement machine, never auto-applied.
            settings["modbus_writes_enabled"] = False
            config = work / "settings.json"
            config.write_text(json.dumps(settings), encoding="utf-8")
            if (
                database.stat().st_size + config.stat().st_size
                > self.settings.backup_max_expanded_mb * 1024**2
            ):
                raise BackupError("Database dump exceeds configured expanded backup size limit")
            manifest = Manifest(
                created_at=info.created_at,
                application_version=APP_VERSION,
                migration_revision=revision,
                deployment_mode=self.settings.application_mode,
                postgres_major=major,
                files={
                    "database.dump": digest_file(database),
                    "configuration/settings.json": digest_file(config),
                },
            )
            (work / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
            archive = work / "payload.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for path, name in (
                    (database, "database.dump"),
                    (config, "configuration/settings.json"),
                    (work / "manifest.json", "manifest.json"),
                ):
                    tar.add(path, arcname=name, recursive=False)
            final = self.path(info.id, ".mmbak")
            encrypt(archive, final, password)
            if final.stat().st_size > self.settings.backup_max_upload_mb * 1024**2:
                final.unlink()
                raise BackupError("Encrypted backup exceeds configured backup size limit")
            info.status, info.manifest, info.size = "AVAILABLE", manifest, final.stat().st_size
            self.write(info)
        self.retain()
        return info

    def validate(self, identifier: UUID, password: str, major: int) -> BackupInfo:
        info = self.read(identifier)
        with TemporaryDirectory(prefix="validate-", dir=self.root) as directory:
            work = Path(directory)
            manifest = unpack(
                self.path(identifier, ".mmbak"),
                work,
                password,
                self.settings.backup_max_upload_mb * 1024**2,
                self.settings.backup_max_expanded_mb * 1024**2,
            )
            check_revision(manifest.migration_revision)
            if manifest.deployment_mode != self.settings.application_mode:
                raise BackupError("Backup deployment mode does not match this installation")
            if manifest.postgres_major != major:
                raise BackupError("Restore requires the same PostgreSQL major version")
            validate_dump(self.settings, work / "database.dump")
            info.manifest, info.status, info.error = manifest, "VALIDATED", None
            self.write(info)
        return info
