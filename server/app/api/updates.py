"""ADMIN and CSRF authorization is applied centrally to every updater route."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from filelock import Timeout
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.version import APP_VERSION
from app.db.session import get_session
from app.updates.github import GitHubReleases
from app.updates.prepare import prepare
from app.updates.schema import ACTIVE, InstallRequest, UpdateStatus, semver
from app.updates.store import UpdateStore

router = APIRouter(prefix="/api/system/updates", tags=["updates"])
logger = logging.getLogger(__name__)


def store_for(request: Request) -> UpdateStore:
    return UpdateStore(request.app.state.settings.update_directory)


def public_status(request: Request, status: UpdateStatus) -> UpdateStatus:
    settings = request.app.state.settings
    result = status.model_copy(deep=True)
    result.installed_version = APP_VERSION
    result.available = bool(result.release and semver(result.release.version) > semver(APP_VERSION))
    result.runner_available = store_for(request).runner_alive()
    result.install_supported = settings.update_enabled and settings.application_mode == "cloud"
    if not result.install_supported:
        result.message = "Installation requires the opt-in Cloud Compose host runner. Native Edge updates remain operator-managed."
    return result


@router.get("/status", response_model=UpdateStatus)
async def status(request: Request) -> UpdateStatus:
    try:
        return public_status(request, store_for(request).read())
    except Exception:
        raise HTTPException(503, "Update journal unavailable; inspect host storage") from None


@router.post("/check", response_model=UpdateStatus)
async def check(request: Request, session: AsyncSession = Depends(get_session)) -> UpdateStatus:
    store = store_for(request)
    try:
        with store.lock():
            status = store.read()
            if status.state in ACTIVE or status.recovery_required:
                raise HTTPException(409, "An update is active or requires operator recovery")
            store.write(status, state="CHECKING", error=None, failure_stage=None)
            try:
                async with (
                    asyncio.timeout(90),
                    httpx.AsyncClient(timeout=30, trust_env=False) as client,
                ):
                    release = await GitHubReleases(
                        request.app.state.settings.update_repository, client
                    ).latest()
                available = bool(release and semver(release.version) > semver(APP_VERSION))
                store.write(
                    status,
                    release=release,
                    last_checked=datetime.now(UTC),
                    state="AVAILABLE" if available else "IDLE",
                )
                await session.commit()
            except Exception as exc:
                logger.warning("Release check failed (%s)", type(exc).__name__)
                store.write(
                    status,
                    state="FAILED",
                    failure_stage="CHECKING",
                    error="Release check failed; verify repository, stable release assets and connectivity",
                )
            return public_status(request, status)
    except Timeout:
        raise HTTPException(409, "Updater is busy") from None


@router.post("/install", response_model=UpdateStatus, status_code=202)
async def install(
    payload: InstallRequest,
    request: Request,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> UpdateStatus:
    store = store_for(request)
    try:
        with store.lock():
            status = public_status(request, store.read())
            if not status.install_supported or not status.runner_available:
                raise HTTPException(
                    409, "A supported host deployment runner must be configured and online"
                )
            if status.state in ACTIVE or status.recovery_required:
                raise HTTPException(409, "An update is active or requires operator recovery")
            if not status.available or status.release.version != payload.version:
                raise HTTPException(409, "Check for a newer release before requesting installation")
            status = UpdateStatus(
                installed_version=APP_VERSION,
                from_version=APP_VERSION,
                state="DOWNLOADING",
                release=status.release,
                job_id=uuid4(),
                last_checked=status.last_checked,
                requested_by=request.state.user.id,
            )
            await session.commit()
            store.write(status)
            background.add_task(
                prepare, request.app.state.settings, status, payload.passphrase.get_secret_value()
            )
            return public_status(request, status)
    except Timeout:
        raise HTTPException(409, "Updater is busy") from None
