"""Run only inside a disposable PostgreSQL installation (see compose_backup_smoke.py)."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.main import create_app
from app.models import (
    AuthSession,
    Command,
    Connection,
    RecoveryState,
    Tag,
    TagCurrentValue,
    TagHistory,
    User,
)
from app.restore import restore
from app.services.auth import hash_password
from app.services.backup_archive import BackupError
from app.services.backup_postgres import alembic_config
from app.services.backup_store import BackupStore
from app.services.current_values import Reading, upsert_current


async def main() -> None:
    settings = Settings()
    assert settings.postgres_db.startswith("backup_test_")
    assert settings.application_mode == "standalone" and not settings.modbus_writes_enabled
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:

        def migrations(sync_connection):
            config = alembic_config()
            config.attributes["connection"] = sync_connection
            command.upgrade(config, "head")
            command.downgrade(config, "0013_realtime_sync")
            command.upgrade(config, "head")
            command.check(config)

        await connection.run_sync(migrations)
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            User(
                username="backup_admin",
                password_hash=hash_password("isolated-admin-test"),
                role="ADMIN",
                enabled=True,
            )
        )
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120
        ) as api,
    ):
        login = await api.post(
            "/api/auth/login", json={"username": "backup_admin", "password": "isolated-admin-test"}
        )
        assert login.status_code == 200, login.text
        api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]

        async def post(path, payload):
            result = await api.post("/api/" + path, json=payload)
            assert result.status_code in (200, 201), result.text
            return result.json()

        connection = await post(
            "connections",
            {"name": "Isolated bus", "protocol": "modbus_tcp", "host": "test.invalid"},
        )
        device = await post(
            "devices", {"name": "Test unit", "connection_id": connection["id"], "slave_id": 1}
        )
        tag = await post(
            "tags",
            {
                "name": "Before backup",
                "key": "reading",
                "device_id": device["id"],
                "register_type": "coil",
                "data_type": "bool",
                "address": 0,
                "writable": True,
                "history_enabled": True,
            },
        )
        now = datetime.now(UTC)
        async with AsyncSession(engine) as session, session.begin():
            await upsert_current(session, tag["id"], reading=Reading(True, now, source="simulator"))
            session.add(
                Command(
                    tag_id=tag["id"],
                    request_id=str(uuid4()),
                    requested_boolean=False,
                    status="QUEUED",
                    source="manual",
                    telemetry_mode="simulator",
                    created_at=now,
                    expires_at=now + timedelta(minutes=1),
                    tag_version=now,
                    device_version=now,
                    connection_version=now,
                )
            )
        exported = await post("system/configuration/export", {})
        assert len(exported["data"]["tags"]) == 1
        # Real PostgreSQL preview checks/rolls back schema constraints and advisory/table locks.
        preview = {
            **exported,
            "data": {"locations": [{"id": str(uuid4()), "values": {"name": "Import preview"}}]},
        }
        await post("system/configuration/preview", preview)
        assert not (await api.get("/api/locations")).json()
        passphrase = "isolated-encrypted-backup-passphrase"
        backup = await post("system/backups", {"passphrase": passphrase})
        key = backup["id"]
        assert backup["manifest"]["migration_revision"] == "0014_backups"
        downloaded = await api.get(f"/api/system/backups/{key}/download")
        assert (
            downloaded.content.startswith(b"MMBACKUP\x01")
            and b"isolated-admin-test" not in downloaded.content
        )
        assert (
            await api.post(
                f"/api/system/restores/{key}/validate", json={"passphrase": "incorrect-password"}
            )
        ).status_code == 400
        await post(f"system/restores/{key}/validate", {"passphrase": passphrase})
        await post(f"system/restores/{key}/confirm", {"confirmation": "RESTORE"})
        assert (await api.delete(f"/api/system/backups/{key}")).status_code == 400
        # A live application must block restore, leaving the original database untouched.
        try:
            await restore(settings, UUID(key), passphrase)
            raise AssertionError("Live database restore should be refused")
        except BackupError as exc:
            assert "Database is in use" in str(exc)
        await post(f"system/restores/{key}/validate", {"passphrase": passphrase})
        await post(f"system/restores/{key}/confirm", {"confirmation": "RESTORE"})
        result = await api.patch(f"/api/tags/{tag['id']}", json={"name": "After backup"})
        assert result.status_code == 200
    await engine.dispose()
    previous = await restore(settings, UUID(key), passphrase)
    assert previous.startswith("mm_previous_")
    engine = create_async_engine(settings.database_url)
    async with AsyncSession(engine) as session:
        assert (await session.get(Tag, tag["id"])).name == "Before backup"
        assert (await session.get(Connection, connection["id"])).name == "Isolated bus"
        assert await session.scalar(select(func.count()).select_from(TagHistory)) == 1
        assert (await session.get(TagCurrentValue, tag["id"])).quality == "STALE"
        assert (await session.scalar(select(Command))).status == "EXPIRED"
        assert await session.scalar(select(func.count()).select_from(AuthSession)) == 0
        assert not (await session.get(RecoveryState, 1)).sync_review_required
        assert (
            await session.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": previous}
            )
            == 1
        )
    await engine.dispose()
    assert BackupStore(settings).read(key).status == "SUCCESS"
    recovered_app = create_app(settings)
    async with (
        recovered_app.router.lifespan_context(recovered_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=recovered_app), base_url="http://test"
        ) as api,
    ):
        assert (await api.get("/api/health/db")).status_code == 200
        login = await api.post(
            "/api/auth/login", json={"username": "backup_admin", "password": "isolated-admin-test"}
        )
        assert login.status_code == 200
        assert (await api.get(f"/api/tags/{tag['id']}")).json()["name"] == "Before backup"
    print(
        "PASS: migration upgrade/downgrade/check; PostgreSQL preview rollback; encrypted backup; download; validation; live restore refusal; staged offline restore; original database retained; history preserved; commands expired; sessions revoked; health verified"
    )


if __name__ == "__main__":
    asyncio.run(main())
