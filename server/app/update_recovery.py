"""Explicit offline updater recovery using unchanged Phase 12 validation/staged restore."""

import argparse
import asyncio
import getpass
import shutil
from uuid import UUID

from sqlalchemy import text

from app.core.config import Settings
from app.db.session import Database
from app.restore import restore
from app.services.backup_archive import BackupError
from app.services.backup_store import BackupStore, blocking
from app.updates.artifact import sha256
from app.updates.store import UpdateError, UpdateStore


async def recover(settings: Settings, job_id: UUID, password: str) -> str:
    if settings.modbus_writes_enabled:
        raise UpdateError("Offline recovery requires physical writes disabled by the operator")
    journal = UpdateStore(settings.update_directory)
    with journal.lock():
        status = journal.read()
        if status.job_id != job_id or not status.recovery_required or not status.backup_id:
            raise UpdateError("This job is not awaiting controlled recovery")
        source = journal.job(job_id) / "recovery.mmbak"
        if source.is_symlink() or not source.is_file():
            raise UpdateError("Pinned recovery backup unavailable")
        if await blocking(sha256, source) != status.backup_sha256:
            raise UpdateError("Pinned recovery backup integrity check failed")
        artifacts = BackupStore(settings)
        # Register a fresh upload with normal backup metadata. Do not overwrite an old backup.
        with artifacts.lock():
            info = artifacts.new("upload")
            with artifacts.lock(info.id):
                await blocking(shutil.copyfile, source, artifacts.path(info.id, ".mmbak"))
                info.size = source.stat().st_size
                artifacts.write(info)
                database = Database(settings)
                try:
                    async with database.sessions() as session:
                        major = int(await session.scalar(text("SHOW server_version_num"))) // 10000
                    await blocking(artifacts.validate, info.id, password, major)
                finally:
                    await database.close()
                info = artifacts.read(info.id)
                info.status = "READY_OFFLINE"
                artifacts.write(info)
        # Phase 12 refuses active DB clients, validates in a staging DB, retains replaced DB,
        # expires unfinished commands and sets the Edge/Cloud sync reconciliation fence.
        previous = await restore(settings, info.id, password)
        journal.write(
            status,
            message="Database restored through Phase 12. Verify retained previous images and reconcile synchronization before resuming. Recovery remains operator-controlled.",
        )
        return previous


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=UUID, required=True)
    parser.add_argument("--confirm", choices=["RESTORE"], required=True)
    args = parser.parse_args()
    try:
        previous = asyncio.run(
            recover(Settings(), args.job, getpass.getpass("Backup passphrase: "))
        )
        print(
            f"Staged restore complete. Retained database: {previous}. Verify, then reconcile before resume sync."
        )
    except (BackupError, UpdateError) as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        raise SystemExit(
            "Offline recovery failed; inspect backup state and database access. Secrets suppressed."
        ) from None


if __name__ == "__main__":
    main()
