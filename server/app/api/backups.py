"""ADMIN backup artifacts and transactional configuration transfer. No live DB restore."""

import json
import logging
import os
from contextlib import ExitStack, asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.db.session import get_session
from app.schemas.backup import (
    BackupInfo,
    BackupPassword,
    ConfigurationDocument,
    ConfirmRestore,
    ImportRequest,
)
from app.services.backup_archive import MAGIC, BackupError
from app.services.backup_store import BackupStore, blocking
from app.services.configuration_transfer import export_configuration, import_configuration

router = APIRouter(prefix="/api/system", tags=["backup"])
logger = logging.getLogger(__name__)


@asynccontextmanager
async def guarded(session: AsyncSession):
    try:
        yield
    except HTTPException:
        await session.rollback()
        raise
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(
            422, [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        ) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            409, "Configuration conflicts with existing records or database constraints"
        ) from None
    except BackupError as exc:
        await session.rollback()
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:
        await session.rollback()
        # Database/OS exceptions can contain credentials; never print exception details here.
        logger.error("Backup operation failed (%s)", type(exc).__name__)
        raise HTTPException(
            503, "Backup operation failed; check disk space, database and backup tool availability"
        ) from None


def store(request: Request) -> BackupStore:
    return BackupStore(request.app.state.settings)


async def postgres_major(session: AsyncSession) -> int:
    return int(await session.scalar(text("SHOW server_version_num"))) // 10000


@router.get("/backups", response_model=list[BackupInfo])
async def list_backups(request: Request, session: AsyncSession = Depends(get_session)):
    async with guarded(session):
        return store(request).listing()


@router.post("/backups", response_model=BackupInfo, status_code=201)
async def create_backup(
    payload: BackupPassword, request: Request, session: AsyncSession = Depends(get_session)
):
    async with guarded(session):
        artifacts = store(request)
        with artifacts.lock():
            info = artifacts.new("backup")
            with artifacts.lock(info.id):
                try:
                    await session.execute(text("LOCK TABLE alembic_version IN SHARE MODE"))
                    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
                    major = await postgres_major(session)
                    snapshot = await session.scalar(text("SELECT pg_export_snapshot()"))
                    result = await blocking(
                        artifacts.create,
                        info,
                        payload.passphrase.get_secret_value(),
                        revision,
                        major,
                        snapshot,
                    )
                    await session.commit()
                    return result
                except BaseException:
                    info.status, info.error = "FAILED", "Backup creation did not complete"
                    artifacts.write(info)
                    raise


@router.post("/backups/upload", response_model=BackupInfo, status_code=201)
async def upload_backup(request: Request, session: AsyncSession = Depends(get_session)):
    async with guarded(session):
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise HTTPException(415, "Upload an encrypted .mmbak file as application/octet-stream")
        artifacts = store(request)
        maximum = artifacts.settings.backup_max_upload_mb * 1024**2
        with artifacts.lock():
            info = artifacts.new("upload")
            with artifacts.lock(info.id):
                path = artifacts.path(info.id, ".mmbak")
                try:
                    with path.open("xb") as output:
                        os.chmod(path, 0o600)
                        async for chunk in request.stream():
                            info.size += len(chunk)
                            if info.size > maximum:
                                raise HTTPException(413, "Backup exceeds upload size limit")
                            output.write(chunk)
                    with path.open("rb") as source:
                        if source.read(len(MAGIC)) != MAGIC:
                            raise HTTPException(422, "Not a supported encrypted backup")
                    artifacts.write(info)
                    await session.commit()
                    return info
                except BaseException:
                    path.unlink(missing_ok=True)
                    artifacts.path(info.id, ".json").unlink(missing_ok=True)
                    raise


@router.get("/backups/{identifier}/download")
async def download_backup(
    identifier: UUID, request: Request, session: AsyncSession = Depends(get_session)
):
    async with guarded(session):
        artifacts = store(request)
        locks = ExitStack()
        try:
            locks.enter_context(artifacts.lock(identifier))
            info = artifacts.read(identifier)
            if info.status in ("CREATING", "RESTORING", "FAILED"):
                raise HTTPException(409, "Backup is not available for download")
            file = locks.enter_context(artifacts.path(identifier, ".mmbak").open("rb"))
        except BaseException:
            locks.close()
            raise

        async def stream():
            try:
                while chunk := await blocking(file.read, 1024 * 1024):
                    yield chunk
            finally:
                locks.close()

        return StreamingResponse(
            stream(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="backup-{identifier}.mmbak"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
            background=BackgroundTask(locks.close),
        )


@router.delete("/backups/{identifier}", status_code=204)
async def delete_backup(
    identifier: UUID, request: Request, session: AsyncSession = Depends(get_session)
):
    async with guarded(session):
        store(request).delete(identifier)
        await session.commit()


@router.post("/restores/{identifier}/validate", response_model=BackupInfo)
async def validate_restore(
    identifier: UUID,
    payload: BackupPassword,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    async with guarded(session):
        artifacts = store(request)
        with artifacts.lock(identifier):
            result = await blocking(
                artifacts.validate,
                identifier,
                payload.passphrase.get_secret_value(),
                await postgres_major(session),
            )
            await session.commit()
            return result


@router.post("/restores/{identifier}/confirm", response_model=BackupInfo)
async def confirm_restore(
    identifier: UUID,
    payload: ConfirmRestore,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    async with guarded(session):
        artifacts = store(request)
        with artifacts.lock(identifier):
            info = artifacts.read(identifier)
            if info.status != "VALIDATED":
                raise HTTPException(409, "Validate this backup before confirming restore")
            info.status = "READY_OFFLINE"
            artifacts.write(info)
            await session.commit()
            return info


@router.post("/restores/{identifier}/cancel", response_model=BackupInfo)
async def cancel_restore(
    identifier: UUID, request: Request, session: AsyncSession = Depends(get_session)
):
    async with guarded(session):
        artifacts = store(request)
        with artifacts.lock(identifier):
            info = artifacts.read(identifier)
            if info.status not in ("READY_OFFLINE", "CREATING", "RESTORING"):
                raise HTTPException(409, "No restore preparation to cancel")
            # An active operation holds this artifact lock. These are interrupted/prepared jobs only.
            info.status, info.error = (
                "FAILED",
                "Preparation cancelled; validate again before restoring",
            )
            artifacts.write(info)
            await session.commit()
            return info


def local_only(request: Request) -> None:
    if request.app.state.settings.application_mode == "cloud":
        raise HTTPException(
            409,
            "Configuration export/import belongs to the authoritative Edge or standalone installation",
        )


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackupError("JSON contains duplicate keys")
        result[key] = value
    return result


async def read_json(request: Request) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Configuration must be application/json")
    content = bytearray()
    maximum = request.app.state.settings.configuration_max_upload_mb * 1024**2
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > maximum:
            raise HTTPException(413, "Configuration exceeds upload size limit")
    try:
        return json.loads(
            content,
            object_pairs_hook=unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(BackupError("Non-finite JSON value")),
        )
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError("Invalid JSON configuration") from None


@router.post("/configuration/export", response_model=ConfigurationDocument)
async def export(request: Request, session: AsyncSession = Depends(get_session)):
    local_only(request)
    async with guarded(session):
        result = await export_configuration(session)
        await session.commit()
        return result


@router.post("/configuration/preview")
async def preview(request: Request, session: AsyncSession = Depends(get_session)):
    local_only(request)
    async with guarded(session):
        document = ConfigurationDocument.model_validate(await read_json(request))
        # Run exactly the apply validations, including database constraints; commit nothing.
        transaction = await session.begin_nested()
        try:
            counts = await import_configuration(session, document)
        finally:
            await transaction.rollback()
        await session.commit()  # Audit only.
        return {
            "valid": True,
            "counts": counts,
            "warnings": [
                "Imported connections, Automation and Alarm rules are disabled. Review before enabling."
            ],
        }


@router.post("/configuration/import")
async def apply_import(request: Request, session: AsyncSession = Depends(get_session)):
    local_only(request)
    async with guarded(session):
        payload = ImportRequest.model_validate(await read_json(request))
        counts = await import_configuration(session, payload.document)
        await session.commit()
        return {"imported": counts}
