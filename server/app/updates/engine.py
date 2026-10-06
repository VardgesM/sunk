"""Deployment state machine. No shell, Modbus, automation or database downgrade here."""

import logging
from typing import Protocol

from app.updates.schema import UpdateStatus
from app.updates.store import UpdateError, UpdateStore

logger = logging.getLogger(__name__)


class Deployment(Protocol):
    def preserve_and_build(self, status: UpdateStatus) -> None: ...
    def stop(self, status: UpdateStatus) -> None: ...
    def migrate(self, status: UpdateStatus) -> None: ...
    def start(self, status: UpdateStatus, *, previous: bool = False) -> None: ...
    def verify(self, status: UpdateStatus, *, previous: bool = False) -> None: ...


def rollback(store: UpdateStore, status: UpdateStatus, deployment: Deployment) -> None:
    if not status.services_stopped:
        store.write(status, state="FAILED", message="Existing application was not stopped")
        return
    store.write(status, state="ROLLING_BACK")
    try:
        deployment.stop(status)
        if status.migration_started:
            # Even a failed migration can have nontransactional side effects. A revision check
            # alone cannot prove old binaries safe. Keep ingress stopped and require offline restore.
            store.write(
                status,
                state="FAILED",
                recovery_required=True,
                message="Migration was attempted. Services remain stopped; use the encrypted backup and controlled offline recovery. No automatic downgrade or database replacement was attempted.",
            )
            return
        deployment.start(status, previous=True)
        deployment.verify(status, previous=True)
        store.write(
            status,
            state="ROLLED_BACK",
            message="Previous images restarted and verified; database was not migrated",
        )
    except Exception as exc:
        logger.error("Update rollback failed (%s)", type(exc).__name__)
        store.write(
            status,
            state="FAILED",
            recovery_required=True,
            message="Rollback could not be verified; operator recovery required",
        )


def install(store: UpdateStore, status: UpdateStatus, deployment: Deployment) -> None:
    try:
        store.write(
            status,
            state="INSTALLING",
            message="Preserving previous images and building validated release",
        )
        deployment.preserve_and_build(status)
        # Journal the intent BEFORE stopping services; interruption must never be mistaken for success.
        store.write(status, services_stopped=True)
        deployment.stop(status)
        store.write(status, state="MIGRATING")
        if status.release.manifest.migration_revision != status.previous_revision:
            store.write(status, migration_started=True)
            deployment.migrate(status)
        store.write(status, state="RESTARTING")
        deployment.start(status)
        store.write(status, state="VERIFYING")
        deployment.verify(status)
        store.write(
            status,
            state="SUCCESS",
            installed_version=status.release.version,
            message="Application version, database revision, mode and service health verified",
        )
    except Exception as exc:
        logger.error("Update installation failed at %s (%s)", status.state, type(exc).__name__)
        store.write(
            status,
            failure_stage=status.state,
            error=str(exc)
            if isinstance(exc, UpdateError)
            else "Installation or health verification failed; detailed subprocess output is intentionally not exposed",
        )
        rollback(store, status, deployment)


def interrupted(store: UpdateStore, status: UpdateStatus, deployment: Deployment) -> None:
    store.write(
        status,
        failure_stage=status.state,
        error="Previous update was interrupted; installation will not be replayed",
    )
    if status.state == "CHECKING":
        store.write(status, state="FAILED")
        return
    rollback(store, status, deployment)
