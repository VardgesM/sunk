"""Backup safety tests use isolated files/SQLite; real pg_dump/restore has its own smoke test."""

import copy
import io
import json
import tarfile
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models import Connection, Device, Location, RecoveryState, Tag, User
from app.schemas.backup import APP_VERSION, ConfigurationDocument, Manifest
from app.services.backup_archive import BackupError, digest_file, encrypt, unpack
from app.services.backup_store import BackupStore
from app.services.configuration_transfer import (
    export_configuration,
    import_configuration,
)
from app.services.recovery import sync_blocked
from tests.test_configuration import setup_tag

PASSWORD = "test-backup-passphrase-only"
pytestmark = pytest.mark.anyio


def settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        postgres_password="never-export-me",
        backup_directory=str(tmp_path),
        sync_token="secret-machine-token",
        telegram_bot_token="secret-bot-token",
        **overrides,
    )


def document(**groups):
    return ConfigurationDocument(
        exported_at=datetime.now(UTC), application_version=APP_VERSION, data=groups
    )


def graph():
    loc, conn, device, tag, rule, alarm, dashboard, widget = [str(uuid4()) for _ in range(8)]
    return document(
        locations=[{"id": loc, "values": {"name": "Room"}}],
        connections=[
            {"id": conn, "values": {"name": "Bus", "protocol": "modbus_tcp", "host": "test.local"}}
        ],
        devices=[
            {
                "id": device,
                "values": {
                    "name": "Unit",
                    "connection_id": conn,
                    "location_id": loc,
                    "slave_id": 1,
                },
            }
        ],
        tags=[
            {
                "id": tag,
                "values": {
                    "name": "Output",
                    "key": "test_output",
                    "device_id": device,
                    "register_type": "coil",
                    "data_type": "bool",
                    "address": 0,
                    "writable": True,
                    "history_enabled": True,
                    "history_mode": "fixed_interval",
                    "history_interval_ms": 10000,
                },
            }
        ],
        automation_rules=[
            {
                "id": rule,
                "values": {
                    "name": "Example",
                    "enabled": True,
                    "conditions": [{"tag_id": tag, "operator": "==", "value": False}],
                    "actions": [{"target_tag_id": tag, "value": True}],
                },
            }
        ],
        alarm_rules=[
            {
                "id": alarm,
                "values": {
                    "name": "Example alarm",
                    "tag_id": tag,
                    "operator": "==",
                    "value": True,
                    "severity": "WARNING",
                    "enabled": True,
                    "notification_enabled": True,
                },
            }
        ],
        dashboards=[
            {
                "id": dashboard,
                "values": {"name": "Overview", "slug": "overview", "is_default": True},
            }
        ],
        widgets=[
            {
                "id": widget,
                "values": {
                    "dashboard_id": dashboard,
                    "type": "boolean",
                    "title": "Output",
                    "tag_ids": [tag],
                    "configuration": {},
                    "layouts": [
                        {"breakpoint": b, "x": 0, "y": 0, "w": 1, "h": 2}
                        for b in ("lg", "md", "sm")
                    ],
                },
            }
        ],
    )


def make_archive(tmp_path, mutate=None, member=None):
    dump = tmp_path / "sample.dump"
    dump.write_bytes(b"test-custom-dump")
    config = tmp_path / "sample.json"
    config.write_text("{}")
    manifest = Manifest(
        created_at=datetime.now(UTC),
        application_version=APP_VERSION,
        migration_revision="0014_backups",
        deployment_mode="standalone",
        postgres_major=17,
        files={
            "database.dump": digest_file(dump),
            "configuration/settings.json": digest_file(config),
        },
    ).model_dump(mode="json")
    if mutate:
        mutate(manifest)
    tarpath = tmp_path / "source.tar.gz"
    with tarfile.open(tarpath, "w:gz") as tar:
        for name, data in {
            "manifest.json": json.dumps(manifest).encode(),
            "database.dump": dump.read_bytes(),
            "configuration/settings.json": config.read_bytes(),
        }.items():
            item = tarfile.TarInfo(name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
        if member:
            tar.addfile(member)
    encrypted = tmp_path / "test.mmbak"
    encrypt(tarpath, encrypted, PASSWORD)
    output = tmp_path / "output"
    output.mkdir()
    return encrypted, output


def test_encrypted_archive_and_manifest(tmp_path):
    source, output = make_archive(tmp_path)
    assert b"test-custom-dump" not in source.read_bytes()
    manifest = unpack(source, output, PASSWORD, 1024**2, 1024**2)
    assert manifest.migration_revision == "0014_backups"
    assert (output / "database.dump").read_bytes() == b"test-custom-dump"


def test_backup_decrypts_on_replacement_without_original_installation(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    source, _ = make_archive(original)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    copied = replacement / "recovery.mmbak"
    copied.write_bytes(source.read_bytes())
    assert PASSWORD.encode() not in copied.read_bytes()
    for name in ("sample.dump", "sample.json", "source.tar.gz", "test.mmbak"):
        (original / name).unlink()
    recovered = replacement / "recovered"
    recovered.mkdir()
    # No database, login, environment credentials or original installation files are used.
    manifest = unpack(copied, recovered, PASSWORD, 1024**2, 1024**2)
    assert (recovered / "database.dump").read_bytes() == b"test-custom-dump"
    assert PASSWORD not in manifest.model_dump_json()


@pytest.mark.parametrize(
    "failure",
    ["password", "corrupt", "version", "checksum", "path", "symlink", "duplicate", "size"],
)
def test_reject_invalid_archives(tmp_path, failure):
    mutate = None
    member = None
    if failure == "version":

        def mutate(m):
            m.update(format_version=999)
    elif failure == "checksum":

        def mutate(m):
            m["files"]["database.dump"].update(sha256="0" * 64)
    elif failure in ("path", "symlink", "duplicate"):
        member = tarfile.TarInfo("../escaped" if failure == "path" else "database.dump")
        if failure == "symlink":
            member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
    source, output = make_archive(tmp_path, mutate, member)
    if failure == "corrupt":
        content = bytearray(source.read_bytes())
        content[-1] ^= 1
        source.write_bytes(content)
    with pytest.raises(BackupError):
        unpack(
            source,
            output,
            "wrong password" if failure == "password" else PASSWORD,
            1024**2,
            1 if failure == "size" else 1024**2,
        )
    assert not (tmp_path / "escaped").exists()


def test_backup_creation_retention_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.backup_store.dump", lambda cfg, path, snap: path.write_bytes(b"PGDMP test")
    )
    store = BackupStore(settings(tmp_path, backup_retention_count=1))
    first = store.new("backup")
    store.create(first, PASSWORD, "0014_backups", 17, "snapshot")
    with store.lock(first.id):
        second = store.new("backup")
        store.create(second, PASSWORD, "0014_backups", 17, "snapshot")
        assert store.path(first.id, ".mmbak").exists()  # download lock prevents retention
    store.retain()
    assert not store.path(first.id, ".mmbak").exists()
    out = tmp_path / "inspect"
    out.mkdir()
    unpack(store.path(second.id, ".mmbak"), out, PASSWORD, 1024**2, 1024**2)
    text = (out / "settings.json").read_text()
    for secret in (
        "never-export-me",
        "secret-machine-token",
        "secret-bot-token",
        "postgres_password",
        "sync_token",
    ):
        assert secret not in text
    store.delete(second.id)
    assert not store.listing()


async def test_graph_import_roundtrip_and_no_secrets(database_sessions):
    from app.models import AlarmRule, AutomationRule, DashboardWidgetTag

    doc = graph()
    async with database_sessions() as session:
        counts = await import_configuration(session, doc)
        await session.commit()
        assert all(count == 1 for count in counts.values())
        assert not (await session.scalar(select(Connection))).enabled
        assert not (await session.scalar(select(AutomationRule))).enabled
        alarm = await session.scalar(select(AlarmRule))
        assert not alarm.enabled and not alarm.notification_enabled
        assert await session.scalar(select(func.count()).select_from(DashboardWidgetTag)) == 1
        exported = await export_configuration(session)
        await session.commit()
        assert exported.data.tags[0].id == doc.data.tags[0].id
        assert exported.data.devices[0].values["connection_id"] == str(doc.data.connections[0].id)
        serialized = exported.model_dump_json()
        for forbidden in (
            "password",
            "token",
            "current_value",
            "sync_outbox",
            "alarm_events",
            "command_history",
        ):
            assert forbidden not in serialized
        assert exported.data.tags[0].values["history_interval_ms"] == 10000


async def test_preview_apply_conflict_and_rollback(api, database_sessions):
    data = graph().model_dump(mode="json")
    response = await api.post("/api/system/configuration/preview", json=data)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["tags"] == 1
    async with database_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Connection)) == 0
    invalid = copy.deepcopy(data)
    invalid["data"]["tags"][0]["values"]["address"] = -1
    response = await api.post(
        "/api/system/configuration/import", json={"document": invalid, "confirmation": "IMPORT"}
    )
    assert response.status_code == 422, response.text
    async with database_sessions() as session:
        for model in (Location, Connection, Device, Tag):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    response = await api.post(
        "/api/system/configuration/import", json={"document": data, "confirmation": "IMPORT"}
    )
    assert response.status_code == 200, response.text
    conflict = await api.post("/api/system/configuration/preview", json=data)
    assert conflict.status_code == 400 and "conflict" in conflict.text


@pytest.mark.parametrize(
    "problem", ["cycle", "reference", "type", "duplicate", "secret", "version"]
)
async def test_bad_configuration(api, problem):
    data = graph().model_dump(mode="json")
    if problem == "cycle":
        data["data"]["locations"][0]["values"]["parent_id"] = data["data"]["locations"][0]["id"]
    elif problem == "reference":
        data["data"]["devices"][0]["values"]["connection_id"] = str(uuid4())
    elif problem == "type":
        data["data"]["automation_rules"][0]["values"]["conditions"][0]["value"] = 3
    elif problem == "duplicate":
        data["data"]["tags"].append(data["data"]["tags"][0])
    elif problem == "secret":
        data["data"]["users"] = [{"password_hash": "malicious"}]
    else:
        data["version"] = 999
    assert (await api.post("/api/system/configuration/preview", json=data)).status_code in (
        400,
        422,
    )


async def test_export_api_and_natural_key_conflict(api):
    await setup_tag(api)
    first = await api.post("/api/system/configuration/export")
    second = await api.post("/api/system/configuration/export")
    assert first.status_code == 200, first.text
    assert first.json()["data"] == second.json()["data"]
    data = graph().model_dump(mode="json")
    data["data"]["tags"][0]["values"]["key"] = "test_reading"
    assert "tags.key" in (await api.post("/api/system/configuration/preview", json=data)).text


@pytest.mark.parametrize("role", ["OPERATOR", "VIEWER"])
async def test_admin_only_and_csrf(api, database_sessions, role):
    async with database_sessions() as session:
        user = await session.scalar(select(User))
        user.role = role
        await session.commit()
    for method, path in [
        ("GET", "backups"),
        ("GET", f"backups/{uuid4()}/download"),
        ("POST", "configuration/export"),
        ("POST", "backups/upload"),
    ]:
        assert (await api.request(method, "/api/system/" + path)).status_code == 403


async def test_csrf_and_cloud_restriction(api):
    assert (
        await api.post("/api/system/configuration/export", headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    api._transport.app.state.settings.application_mode = "cloud"
    assert (await api.post("/api/system/configuration/export")).status_code == 409
    assert (await api.post("/api/system/configuration/import", json={})).status_code == 409


async def test_upload_download_delete_validation(api, tmp_path):
    api._transport.app.state.settings.backup_directory = str(tmp_path / "artifacts")
    archive, _ = make_archive(tmp_path)
    response = await api.post(
        "/api/system/backups/upload",
        content=archive.read_bytes(),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201, response.text
    key = response.json()["id"]
    assert len((await api.get("/api/system/backups")).json()) == 1
    downloaded = await api.get(f"/api/system/backups/{key}/download")
    assert downloaded.content == archive.read_bytes()
    assert downloaded.headers["cache-control"] == "no-store"
    assert (
        await api.post(f"/api/system/restores/{key}/confirm", json={"confirmation": "RESTORE"})
    ).status_code == 409
    assert (await api.delete(f"/api/system/backups/{key}")).status_code == 204
    assert not (await api.get("/api/system/backups")).json()
    bad = await api.post(
        "/api/system/backups/upload",
        content=b"not a backup",
        headers={"Content-Type": "application/octet-stream"},
    )
    assert bad.status_code == 422
    assert not (await api.get("/api/system/backups")).json()


async def test_size_json_duplicate_and_recovery_fence(api, tmp_path, database_sessions):
    cfg = api._transport.app.state.settings
    cfg.backup_directory, cfg.backup_max_upload_mb = str(tmp_path), 1
    response = await api.post(
        "/api/system/backups/upload",
        content=b"x" * (1024**2 + 1),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert not list(tmp_path.glob("*.mmbak"))
    response = await api.post(
        "/api/system/configuration/preview",
        content='{"data":{},"data":{}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    async with database_sessions() as session:
        assert not await sync_blocked(session)
        session.add(
            RecoveryState(
                id=1,
                restored_at=datetime.now(UTC),
                backup_id=str(uuid4()),
                sync_review_required=True,
            )
        )
        await session.commit()
        assert await sync_blocked(session)


@pytest.mark.parametrize("mode", ["standalone", "edge", "cloud"])
async def test_transfer_mode_and_backup_access(api, tmp_path, mode):
    api._transport.app.state.settings.application_mode = mode
    api._transport.app.state.settings.backup_directory = str(tmp_path)
    assert (await api.get("/api/system/backups")).status_code == 200
    assert (await api.post("/api/system/configuration/export")).status_code == (
        409 if mode == "cloud" else 200
    )


@pytest.mark.parametrize("change", ["mode", "major", "revision"])
def test_restore_compatibility(tmp_path, monkeypatch, change):
    monkeypatch.setattr("app.services.backup_store.validate_dump", lambda *args: None)

    def mutate(manifest):
        manifest[
            {
                "mode": "deployment_mode",
                "major": "postgres_major",
                "revision": "migration_revision",
            }[change]
        ] = {"mode": "cloud", "major": 18, "revision": "unknown_revision"}[change]

    archive, _ = make_archive(tmp_path, mutate)
    store = BackupStore(settings(tmp_path / "store"))
    info = store.new("upload")
    store.path(info.id, ".mmbak").write_bytes(archive.read_bytes())
    with pytest.raises(BackupError):
        store.validate(info.id, PASSWORD, 17)


async def test_restore_validation_and_confirmation_api(
    api, tmp_path, monkeypatch, database_sessions
):
    from unittest.mock import AsyncMock

    from app.models import AuditLog

    cfg = api._transport.app.state.settings
    cfg.backup_directory = str(tmp_path / "store")
    monkeypatch.setattr("app.api.backups.postgres_major", AsyncMock(return_value=17))
    monkeypatch.setattr("app.services.backup_store.validate_dump", lambda *args: None)
    archive, _ = make_archive(tmp_path)
    store = BackupStore(cfg)
    info = store.new("upload")
    store.path(info.id, ".mmbak").write_bytes(archive.read_bytes())
    path = f"/api/system/restores/{info.id}"
    response = await api.post(path + "/validate", json={"passphrase": PASSWORD})
    assert response.status_code == 200 and response.json()["status"] == "VALIDATED"
    assert (await api.post(path + "/confirm", json={"confirmation": "wrong"})).status_code == 422
    response = await api.post(path + "/confirm", json={"confirmation": "RESTORE"})
    assert response.status_code == 200 and response.json()["status"] == "READY_OFFLINE"
    assert (await api.delete(f"/api/system/backups/{info.id}")).status_code == 400
    assert (await api.post(path + "/cancel")).status_code == 200
    assert (await api.delete(f"/api/system/backups/{info.id}")).status_code == 204
    async with database_sessions() as session:
        summaries = " ".join(await session.scalars(select(AuditLog.summary)))
        assert str(info.id) in summaries and PASSWORD not in summaries


async def test_malformed_nested_configuration_is_client_error(api):
    data = graph().model_dump(mode="json")
    data["data"]["automation_rules"][0]["values"]["conditions"] = "not-a-list"
    assert (await api.post("/api/system/configuration/preview", json=data)).status_code == 400


async def test_cloud_restore_fence_still_authenticates_machine(api, database_sessions):
    from app.models import EdgeInstallation
    from app.services.auth import digest

    identity = str(uuid4())
    token = "isolated-machine-token-32-characters"
    api._transport.app.state.settings.application_mode = "cloud"
    async with database_sessions() as session:
        session.add(
            EdgeInstallation(id=identity, name="Test Edge", token_hash=digest(token), enabled=True)
        )
        session.add(
            RecoveryState(
                id=1,
                restored_at=datetime.now(UTC),
                backup_id=str(uuid4()),
                sync_review_required=True,
            )
        )
        await session.commit()
    assert (await api.get("/api/sync/v1/requests")).status_code == 401
    response = await api.get(
        "/api/sync/v1/requests", headers={"Authorization": "Bearer " + token, "X-Edge-ID": identity}
    )
    assert response.status_code == 503 and "reconciliation" in response.text


async def test_edge_restore_fence_prevents_network_access(database_sessions, tmp_path):
    from types import SimpleNamespace

    import httpx

    from app.sync.client import SyncClient

    async with database_sessions() as session:
        session.add(
            RecoveryState(
                id=1,
                restored_at=datetime.now(UTC),
                backup_id=str(uuid4()),
                sync_review_required=True,
            )
        )
        await session.commit()

    def forbidden(request):
        raise AssertionError("Restored Edge must not send sync traffic before review")

    cfg = settings(tmp_path, application_mode="edge", sync_cloud_url="https://cloud.example.test")
    cfg.sync_token = __import__("pydantic").SecretStr("isolated-machine-token-32-characters")
    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as http:
        for _ in range(2):
            # A new client/session represents a process restart; the persisted fence remains.
            client = SyncClient(SimpleNamespace(sessions=database_sessions), cfg, http)
            with pytest.raises(ValueError, match="reconciliation"):
                await client.cycle()


async def test_restore_requires_physical_writes_disabled(tmp_path):
    from app.restore import restore

    with pytest.raises(BackupError, match="MODBUS_WRITES_ENABLED=false"):
        await restore(settings(tmp_path, modbus_writes_enabled=True), uuid4(), PASSWORD)


async def test_backup_requires_login(api):
    api.cookies.clear()
    assert (await api.get("/api/system/backups")).status_code == 401


@pytest.mark.parametrize("writes_enabled", [False, True])
async def test_manual_resume_changes_only_fence_after_review(
    database_sessions, tmp_path, monkeypatch, writes_enabled
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.restore import resume_sync

    backup_id = str(uuid4())
    async with database_sessions() as session:
        session.add(
            RecoveryState(
                id=1, restored_at=datetime.now(UTC), backup_id=backup_id, sync_review_required=True
            )
        )
        await session.commit()
    engine = database_sessions.kw["bind"]
    monkeypatch.setattr(
        "app.restore.create_async_engine",
        lambda _: SimpleNamespace(begin=engine.begin, dispose=AsyncMock()),
    )
    cfg = settings(tmp_path, application_mode="edge", modbus_writes_enabled=writes_enabled)
    if writes_enabled:
        with pytest.raises(BackupError, match="physical writes disabled"):
            await resume_sync(cfg)
    else:
        await resume_sync(cfg)
    async with database_sessions() as session:
        assert await sync_blocked(session) is writes_enabled
        assert (await session.get(RecoveryState, 1)).backup_id == backup_id
    assert cfg.modbus_writes_enabled is writes_enabled


def test_resume_cli_requires_explicit_reconciled_confirmation(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from app.restore import main

    resume = AsyncMock()
    monkeypatch.setattr("app.restore.Settings", lambda: settings(tmp_path))
    monkeypatch.setattr("app.restore.resume_sync", resume)
    monkeypatch.setattr("sys.argv", ["app.restore", "--resume-sync", "--confirm", "NOT_REVIEWED"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 1
    resume.assert_not_called()
