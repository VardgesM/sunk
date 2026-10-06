"""Durable journal outside the application DB, readable even after migration failure."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from filelock import FileLock

from app.core.version import APP_VERSION
from app.updates.schema import UpdateStatus


class UpdateError(Exception):
    """Only fixed, public-safe messages may be used with this exception."""


def atomic_json(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise UpdateError("Unsafe updater file")
    temporary = path.with_suffix(".tmp")
    if temporary.is_symlink():
        raise UpdateError("Unsafe updater file")
    with temporary.open("w", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if hasattr(os, "O_DIRECTORY"):
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class UpdateStore:
    def __init__(self, directory: str | Path):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def lock(self) -> FileLock:
        return FileLock(self.root / "operation.lock", timeout=0, thread_local=False)

    def read(self) -> UpdateStatus:
        path = self.root / "status.json"
        if not path.exists():
            return UpdateStatus(installed_version=APP_VERSION)
        if path.is_symlink() or path.stat().st_size > 8 * 1024**2:
            raise UpdateError("Invalid updater journal; operator recovery required")
        return UpdateStatus.model_validate_json(path.read_bytes())

    def write(self, status: UpdateStatus, **changes: object) -> UpdateStatus:
        for field, value in changes.items():
            setattr(status, field, value)
        status.updated_at = datetime.now(UTC)
        atomic_json(self.root / "status.json", status.model_dump(mode="json"))
        return status

    def job(self, identifier: UUID) -> Path:
        path = self.root / str(UUID(str(identifier)))
        if path.is_symlink():
            raise UpdateError("Unsafe update directory")
        path.mkdir(mode=0o700, exist_ok=True)
        return path

    def runner_alive(self) -> bool:
        try:
            path = self.root / "runner.json"
            if path.is_symlink() or path.stat().st_size > 1024:
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            elapsed = (
                datetime.now(UTC) - datetime.fromisoformat(data["heartbeat"])
            ).total_seconds()
            return data["handler"] == "cloud-compose-v1" and 0 <= elapsed < 30
        except (OSError, ValueError, KeyError, TypeError):
            return False
