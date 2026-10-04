"""Controlled offline restore: validate/stage first, preserve the old database for rollback."""

import argparse
import asyncio
import getpass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import asyncpg
from alembic import command
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.models import (
    AuthSession,
    Command,
    RecoveryState,
    RemoteInbox,
    RemoteRequest,
    TagCurrentValue,
)
from app.services.backup_archive import BackupError, unpack
from app.services.backup_postgres import alembic_config, check_revision, run_tool, validate_dump
from app.services.backup_store import BackupStore, blocking


def quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def connect(settings: Settings, database: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        database=database,
        timeout=10,
        command_timeout=settings.backup_timeout_seconds,
    )


async def sanitize(session: AsyncSession, settings: Settings, identifier: UUID) -> None:
    now = datetime.now(UTC)
    await session.execute(delete(AuthSession))
    reason = "Expired by database recovery; equipment state must be verified before a new command"
    await session.execute(
        update(Command)
        .where(Command.status.not_in(["SUCCESS", "FAILED", "CANCELLED", "EXPIRED"]))
        .values(
            status="EXPIRED",
            completed_at=now,
            error_message=reason,
            physical_confirmed=False,
            revision=Command.revision + 1,
        )
    )
    for model in (RemoteRequest, RemoteInbox):
        fields = {"status": "EXPIRED", "error": reason}
        if model is RemoteRequest:
            fields["completed_at"] = now
        await session.execute(
            update(model)
            .where(model.status.not_in(["SUCCESS", "FAILED", "CANCELLED", "EXPIRED"]))
            .values(**fields)
        )
    await session.execute(
        update(TagCurrentValue)
        .where(TagCurrentValue.quality == "GOOD")
        .values(
            quality="STALE",
            error="Restored value awaits a fresh reading",
            revision=TagCurrentValue.revision + 1,
            updated_at=now,
        )
    )
    await session.merge(
        RecoveryState(
            id=1,
            restored_at=now,
            backup_id=str(identifier),
            sync_review_required=settings.application_mode != "standalone",
        )
    )


async def prepare_database(settings: Settings, database: str, identifier: UUID) -> None:
    engine = create_async_engine(
        settings.database_url.set(database=database),
        connect_args={"command_timeout": settings.backup_timeout_seconds},
    )
    try:
        async with engine.begin() as connection:

            def migrate(sync_connection):
                config = alembic_config()
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        async with AsyncSession(engine) as session, session.begin():
            await sanitize(session, settings, identifier)
            # SQL and required schema must be usable before touching the original database.
            await session.scalar(select(Command.id).limit(1))
            await session.scalar(text("SELECT version_num FROM alembic_version"))
    finally:
        await engine.dispose()


async def restore(settings: Settings, identifier: UUID, password: str) -> str:
    if settings.modbus_writes_enabled:
        raise BackupError(
            "Set MODBUS_WRITES_ENABLED=false and stop every API, worker and sync process first"
        )
    artifacts = BackupStore(settings)
    with artifacts.lock(), artifacts.lock(identifier):
        info = artifacts.read(identifier)
        if info.status != "READY_OFFLINE":
            raise BackupError(
                "Validate and explicitly confirm restore through the ADMIN interface first"
            )
        info.status, info.error = "RESTORING", None
        artifacts.write(info)
        maintenance = None
        staged = "mm_restore_" + uuid4().hex[:20]
        previous = "mm_previous_" + uuid4().hex[:20]
        created, swapped, fenced = False, False, False
        try:
            with TemporaryDirectory(prefix="restore-", dir=artifacts.root) as directory:
                work = Path(directory)
                manifest = await blocking(
                    unpack,
                    artifacts.path(identifier, ".mmbak"),
                    work,
                    password,
                    settings.backup_max_upload_mb * 1024**2,
                    settings.backup_max_expanded_mb * 1024**2,
                )
                check_revision(manifest.migration_revision)
                maintenance = await connect(settings, "postgres")
                major = int(await maintenance.fetchval("SHOW server_version_num")) // 10000
                if (
                    manifest.postgres_major != major
                    or manifest.deployment_mode != settings.application_mode
                ):
                    raise BackupError(
                        "Backup PostgreSQL version or deployment mode is incompatible"
                    )
                await blocking(validate_dump, settings, work / "database.dump")
                if await maintenance.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=$1", settings.postgres_db
                ):
                    raise BackupError(
                        "Database is in use; stop ALL API, worker, sync and other database clients"
                    )
                await maintenance.execute(f"CREATE DATABASE {quoted(staged)} TEMPLATE template0")
                created = True
                await blocking(restore_dump, settings, work / "database.dump", staged)
                await prepare_database(settings, staged, identifier)
                # Only now fence new sessions. Existing sessions are never forcefully terminated.
                await maintenance.execute(
                    f"ALTER DATABASE {quoted(settings.postgres_db)} ALLOW_CONNECTIONS false"
                )
                fenced = True
                if await maintenance.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=$1", settings.postgres_db
                ):
                    raise BackupError("A client reconnected during preparation; stop it and retry")
                async with maintenance.transaction():
                    await maintenance.execute(
                        f"ALTER DATABASE {quoted(settings.postgres_db)} RENAME TO {quoted(previous)}"
                    )
                    await maintenance.execute(
                        f"ALTER DATABASE {quoted(staged)} RENAME TO {quoted(settings.postgres_db)}"
                    )
                swapped, fenced = True, False
                check = await connect(settings, settings.postgres_db)
                try:
                    await check.fetchval("SELECT version_num FROM alembic_version")
                finally:
                    await check.close()
                # Non-secret recovery settings are informational; never silently apply host/USB paths.
                artifacts.path(identifier, ".settings.json").write_bytes(
                    (work / "settings.json").read_bytes()
                )
                info.status = "SUCCESS"
                artifacts.write(info)
                return previous
        except BaseException:
            info.status = "FAILED"
            info.error = (
                f"Database switched; verify health or roll back using {previous}"
                if swapped
                else "Restore failed before activation; original database retained"
            )
            artifacts.write(info)
            raise
        finally:
            if maintenance:
                try:
                    if fenced:
                        await maintenance.execute(
                            f"ALTER DATABASE {quoted(settings.postgres_db)} ALLOW_CONNECTIONS true"
                        )
                    if created and not swapped:
                        await maintenance.execute(f"DROP DATABASE {quoted(staged)}")
                finally:
                    await maintenance.close()


def restore_dump(settings: Settings, path: Path, database: str) -> None:
    run_tool(
        settings,
        "pg_restore",
        [
            "--single-transaction",
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            "--dbname=" + database,
            str(path),
        ],
        database=database,
    )


async def resume_sync(settings: Settings) -> None:
    if settings.modbus_writes_enabled:
        raise BackupError("Keep physical writes disabled during recovery reconciliation")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(RecoveryState)
                .where(RecoveryState.id == 1)
                .values(sync_review_required=False)
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=UUID)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--resume-sync", action="store_true")
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.resume_sync:
            if args.confirm != "RECONCILED":
                raise BackupError("After reviewing both databases, confirm with RECONCILED")
            asyncio.run(resume_sync(settings))
            print(
                "Synchronization recovery fence released. Keep writes disabled while verifying catch-up."
            )
        else:
            if args.confirm != "RESTORE" or args.id is None:
                raise BackupError("Use --id BACKUP_UUID --confirm RESTORE")
            previous = asyncio.run(
                restore(settings, args.id, getpass.getpass("Backup passphrase: "))
            )
            print(
                f"Restore complete. Previous database retained as {previous}. Restart services and log in again."
            )
    except BackupError as exc:
        parser.exit(1, str(exc) + "\n")
    except Exception:
        parser.exit(
            1,
            "Restore failed. Check artifact status, database privileges, tools and disk space. Secrets suppressed.\n",
        )


if __name__ == "__main__":
    main()
