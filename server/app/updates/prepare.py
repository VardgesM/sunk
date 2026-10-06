"""API-side preparation. A failure here never stops a running application."""

import asyncio
import logging
import shutil

import httpx
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database
from app.services.backup_store import BackupStore, blocking
from app.updates.artifact import disk_space, sha256, unpack
from app.updates.github import GitHubReleases
from app.updates.schema import UpdateStatus
from app.updates.store import UpdateError, UpdateStore

logger = logging.getLogger(__name__)


async def prepare(settings: Settings, status: UpdateStatus, passphrase: str) -> None:
    store = UpdateStore(settings.update_directory)
    with store.lock():
        database = Database(settings)
        try:
            job = store.job(status.job_id)
            release = status.release
            store.write(status, state="DOWNLOADING")
            async with (
                asyncio.timeout(300),
                httpx.AsyncClient(timeout=30, trust_env=False) as client,
            ):
                await GitHubReleases(settings.update_repository, client).download(
                    release, job / "release.tar.gz"
                )
            store.write(status, state="VALIDATING")
            await blocking(
                unpack,
                job / "release.tar.gz",
                release.manifest,
                job / "validated",
                status.from_version,
            )
            await blocking(disk_space, job, settings.update_disk_reserve_mb * 1024**2)
            store.write(status, state="BACKING_UP")
            artifacts = BackupStore(settings)
            with artifacts.lock():
                info = artifacts.new("backup")
                with artifacts.lock(info.id):
                    try:
                        async with database.sessions() as session:
                            await session.execute(text("LOCK TABLE alembic_version IN SHARE MODE"))
                            revision = await session.scalar(
                                text("SELECT version_num FROM alembic_version")
                            )
                            major = (
                                int(await session.scalar(text("SHOW server_version_num"))) // 10000
                            )
                            snapshot = await session.scalar(text("SELECT pg_export_snapshot()"))
                            await blocking(
                                artifacts.create, info, passphrase, revision, major, snapshot
                            )
                            # Pin encrypted recovery copy independently of normal backup retention/deletion.
                            await blocking(
                                shutil.copyfile,
                                artifacts.path(info.id, ".mmbak"),
                                job / "recovery.mmbak",
                            )
                            await session.commit()
                        store.write(
                            status,
                            backup_id=info.id,
                            previous_revision=revision,
                            backup_sha256=await blocking(sha256, job / "recovery.mmbak"),
                        )
                    except BaseException:
                        info.status, info.error = "FAILED", "Update backup did not complete"
                        artifacts.write(info)
                        raise
            store.write(
                status, state="READY", message="Prepared; waiting for the host deployment runner"
            )
        except BaseException as exc:
            logger.error("Update preparation failed (%s)", type(exc).__name__)
            store.write(
                status,
                state="FAILED",
                failure_stage=status.state,
                error=str(exc)
                if isinstance(exc, UpdateError)
                else "Update preparation failed; current release remains running",
            )
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
        finally:
            await database.close()
