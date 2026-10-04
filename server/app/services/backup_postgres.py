"""PostgreSQL client tools. Credentials travel in environment, never command arguments."""

import os
import subprocess
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import Settings
from app.services.backup_archive import BackupError


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def check_revision(revision: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config())
    if revision not in {r.revision for r in scripts.walk_revisions()}:
        raise BackupError(
            "Unknown or newer database migration; install compatible application code"
        )


def run_tool(
    settings: Settings, tool: str, arguments: list[str], *, database: str | None = None
) -> None:
    environment = {
        **os.environ,
        "PGHOST": settings.postgres_host,
        "PGPORT": str(settings.postgres_port),
        "PGUSER": settings.postgres_user,
        "PGPASSWORD": settings.postgres_password.get_secret_value(),
        "PGDATABASE": database or settings.postgres_db,
        "PGCONNECT_TIMEOUT": "10",
    }
    try:
        result = subprocess.run(
            [tool, *arguments],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=settings.backup_timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        raise BackupError(f"{tool} is not installed on the API/restore host") from None
    except subprocess.TimeoutExpired:
        raise BackupError(f"{tool} exceeded the configured timeout") from None
    except OSError:
        raise BackupError(f"Unable to start {tool}") from None
    if result.returncode:
        raise BackupError(
            f"{tool} failed; check database access, disk space and PostgreSQL tool compatibility"
        )


def dump(settings: Settings, destination: Path, snapshot: str) -> None:
    run_tool(
        settings,
        "pg_dump",
        [
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--snapshot=" + snapshot,
            "--file=" + str(destination),
        ],
    )


def validate_dump(settings: Settings, path: Path) -> None:
    # Decompress/read the entire custom dump, not only its table of contents. Do not execute SQL.
    run_tool(
        settings, "pg_restore", ["--no-owner", "--no-privileges", "--file=" + os.devnull, str(path)]
    )
