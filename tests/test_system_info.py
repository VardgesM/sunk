"""System metadata uses the installed release and the connected database, not head."""

import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest
from alembic.runtime.migration import MigrationContext
from httpx import AsyncClient
from sqlalchemy import text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.version import APP_VERSION
from app.models import User
from app.schemas.backup import APP_VERSION as BACKUP_VERSION
from app.sync.protocol import Heartbeat

pytestmark = pytest.mark.anyio


async def seed_revisions(sessions: async_sessionmaker[AsyncSession], revisions: list[str]) -> None:
    async with sessions.begin() as session:
        await session.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        for revision in revisions:
            await session.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
            )


@pytest.mark.parametrize("mode", ["standalone", "edge", "cloud"])
@pytest.mark.parametrize("role", ["ADMIN", "OPERATOR", "VIEWER"])
async def test_system_info_authenticated_roles_and_modes(
    api: AsyncClient, database_sessions: async_sessionmaker[AsyncSession], mode: str, role: str
) -> None:
    await seed_revisions(database_sessions, ["0013_realtime_sync"])
    async with database_sessions.begin() as session:
        await session.execute(update(User).values(role=role))
    api._transport.app.state.settings.application_mode = mode
    response = await api.get("/api/system/info")
    assert response.status_code == 200
    assert response.json() == {
        "application_version": APP_VERSION,
        "database_revision": "0013_realtime_sync",
        "application_mode": mode,
    }


async def test_revision_is_not_cached_or_inferred_from_migration_files(
    api: AsyncClient, database_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await seed_revisions(database_sessions, ["0013_realtime_sync"])
    assert (await api.get("/api/system/info")).json()["database_revision"] == "0013_realtime_sync"
    async with database_sessions.begin() as session:
        await session.execute(
            text("UPDATE alembic_version SET version_num = :revision"),
            {"revision": "0014_backups"},
        )
    assert (await api.get("/api/system/info")).json()["database_revision"] == "0014_backups"


@pytest.mark.parametrize("empty_table", [True, False])
async def test_uninitialized_revision_is_explicit(
    api: AsyncClient, database_sessions: async_sessionmaker[AsyncSession], empty_table: bool
) -> None:
    if empty_table:
        await seed_revisions(database_sessions, [])
    response = await api.get("/api/system/info")
    assert response.status_code == 200
    assert response.json()["database_revision"] is None


async def test_system_info_requires_login(api: AsyncClient) -> None:
    api.cookies.clear()
    assert (await api.get("/api/system/info")).status_code == 401


async def test_revision_failure_is_reported_without_database_details(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        MigrationContext,
        "get_current_revision",
        Mock(side_effect=OperationalError("query", {}, Exception("private database details"))),
    )
    response = await api.get("/api/system/info")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database revision unavailable"}


async def test_multiple_revisions_are_not_silently_reported_as_one(
    api: AsyncClient, database_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await seed_revisions(database_sessions, ["branch_a", "branch_b"])
    assert (await api.get("/api/system/info")).status_code == 503


async def test_application_version_has_one_release_source(api: AsyncClient) -> None:
    project = Path(__file__).resolve().parents[1] / "server" / "pyproject.toml"
    canonical = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    assert APP_VERSION == BACKUP_VERSION == Heartbeat().software_version == canonical
    assert (await api.get("/openapi.json")).json()["info"]["version"] == canonical
    assert (await api.get("/api/system/info")).json()["application_version"] == canonical
