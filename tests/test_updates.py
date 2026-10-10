"""Updater safety without network, Docker mutations, or physical equipment."""

import io
import tarfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.core.version import APP_VERSION
from app.models import AuditLog
from app.release import build
from app.updates import artifact, prepare
from app.updates.compose import CloudCompose, HostConfig
from app.updates.engine import install, interrupted
from app.updates.github import GitHubReleases
from app.updates.schema import Release, ReleaseManifest, UpdateStatus, semver
from app.updates.store import UpdateError, UpdateStore, atomic_json


@pytest.fixture
def release_files(tmp_path):
    root = tmp_path / "source"
    contents = {
        "server/pyproject.toml": '[project]\nname="modbus-monitor-server"\nversion="1.2.0"\n',
        "server/alembic/versions/base.py": 'revision = "0014_backups"\ndown_revision = None\n',
        "server/Dockerfile": "FROM scratch\n",
        "server/app/main.py": "# test payload only\n",
        "frontend/Dockerfile.production": "FROM scratch\n",
        "frontend/package-lock.json": "{}",
        "frontend/nginx.conf": "# test\n",
    }
    for name, value in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    manifest = build(root, tmp_path / "artifacts", APP_VERSION, list(contents))
    release = Release(
        version=manifest.version,
        tag="v" + manifest.version,
        published_at=datetime.now(UTC),
        notes="Test release",
        manifest=manifest,
    )
    return root, tmp_path / "artifacts/modbus-monitor-1.2.0.tar.gz", release


def job(store, release):
    status = UpdateStatus(
        installed_version=APP_VERSION,
        from_version=APP_VERSION,
        state="READY",
        job_id=uuid4(),
        release=release,
        backup_id=uuid4(),
        previous_revision="0014_backups",
    )
    store.write(status)
    return status


@pytest.mark.parametrize("value", ["1.2", "01.2.3", "1.2.3-beta", "1.2.3;rm", "-1.2.3", "latest"])
def test_rejects_invalid_stable_versions(value):
    with pytest.raises(ValueError):
        semver(value)


def test_release_roundtrip_and_no_secrets(release_files, tmp_path):
    _, archive, release = release_files
    target = tmp_path / "installed"
    artifact.unpack(archive, release.manifest, target, APP_VERSION)
    assert (target / "server/app/main.py").read_text() == "# test payload only\n"
    assert artifact.migration_head(target) == "0014_backups"
    assert not list(target.rglob(".env*"))
    assert "password" not in release.model_dump_json()


def test_actual_migrations_include_annotated_revision_assignments():
    from pathlib import Path

    assert artifact.migration_head(Path(__file__).resolve().parents[1]) == "0014_backups"


@pytest.mark.parametrize("name", ["server/NUL", "server/aux.py", "server/CON/x", "server/file. "])
def test_reserved_windows_paths_are_not_release_files(name):
    assert not artifact.permitted(name)


def test_gzip_expansion_is_bounded_before_tar_parsing(release_files, tmp_path):
    import gzip

    _, archive, release = release_files
    archive.write_bytes(gzip.compress(b"\0" * 1024**2))
    manifest = release.manifest.model_copy(
        update={"sha256": artifact.sha256(archive), "size": archive.stat().st_size}
    )
    with pytest.raises(UpdateError, match="Expanded"):
        artifact.unpack(archive, manifest, tmp_path / "expanded", APP_VERSION)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "server/.env",
        "server/.env.cloud",
        "../x",
        "server/../../x",
        "C:/x",
        "server\\x",
        "/server/x",
        "server/a.key",
        "server/backups/a",
        "frontend/node_modules/a",
        "server/.git/config",
    ],
)
def test_forbidden_release_paths(path):
    assert not artifact.permitted(path)


@pytest.mark.parametrize(
    "change", ["corrupt", "checksum", "minimum", "version", "revision", "format"]
)
def test_rejects_incompatible_artifacts(change, release_files, tmp_path):
    _, archive, release = release_files
    manifest = release.manifest.model_copy(deep=True)
    if change == "format":
        with pytest.raises(ValidationError):
            ReleaseManifest.model_validate({**manifest.model_dump(), "format_version": 2})
        return
    if change == "corrupt":
        archive.write_bytes(b"not a tar archive")
        manifest.sha256, manifest.size = artifact.sha256(archive), archive.stat().st_size
    elif change == "checksum":
        manifest.sha256 = "0" * 64
    elif change == "minimum":
        manifest.minimum_version = "99.0.0"
    elif change == "version":
        manifest.version = "1.3.0"
    else:
        manifest.migration_revision = "different"
    with pytest.raises(UpdateError):
        artifact.unpack(archive, manifest, tmp_path / "bad", APP_VERSION)


@pytest.mark.parametrize("kind", ["symlink", "traversal", "duplicate", "missing"])
def test_archive_structure(kind, release_files, tmp_path):
    _, archive, release = release_files
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(bad, "w:gz") as dest:
        for index, member in enumerate(source):
            if kind == "missing" and index == 0:
                continue
            if index == 0 and kind in {"symlink", "traversal"}:
                malicious = tarfile.TarInfo("../../outside" if kind == "traversal" else member.name)
                malicious.type = tarfile.SYMTYPE
                malicious.linkname = "../../outside"
                dest.addfile(malicious)
            else:
                data = source.extractfile(member).read()
                dest.addfile(member, io.BytesIO(data))
                if kind == "duplicate" and index == 0:
                    dest.addfile(member, io.BytesIO(data))
    manifest = release.manifest.model_copy(
        update={"sha256": artifact.sha256(bad), "size": bad.stat().st_size}
    )
    with pytest.raises(UpdateError):
        artifact.unpack(bad, manifest, tmp_path / "extract", APP_VERSION)
    assert not (tmp_path.parent / "outside").exists()


def test_insufficient_disk_space(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(UpdateError, match="Insufficient"):
        artifact.disk_space(tmp_path, 1024)


@pytest.mark.anyio
async def test_github_release_and_download(release_files, tmp_path):
    _, archive, release = release_files
    seen = []

    def response(request):
        seen.append(str(request.url))
        if request.url.path.endswith("/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": release.tag,
                    "published_at": release.published_at.isoformat(),
                    "body": "Release notes",
                    "assets": [
                        {"name": "modbus-monitor-1.2.0.json", "size": 10},
                        {
                            "name": "modbus-monitor-1.2.0.tar.gz",
                            "size": release.manifest.size,
                            "digest": "sha256:" + release.manifest.sha256,
                        },
                    ],
                },
            )
        if request.url.path.endswith(".json"):
            return httpx.Response(200, content=release.manifest.model_dump_json())
        return httpx.Response(200, content=archive.read_bytes())

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        github = GitHubReleases("VardgesM/sunk", client)
        found = await github.latest()
        assert found.version == release.version
        await github.download(found, tmp_path / "download.tar.gz")
    assert (tmp_path / "download.tar.gz").read_bytes() == archive.read_bytes()
    assert all(
        url.startswith(
            (
                "https://api.github.com/repos/VardgesM/sunk/",
                "https://github.com/VardgesM/sunk/releases/",
            )
        )
        for url in seen
    )


@pytest.mark.anyio
async def test_no_release_or_unsafe_redirect():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404))
    ) as client:
        assert await GitHubReleases("VardgesM/sunk", client).latest() is None
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        )
    ) as client:
        with pytest.raises(UpdateError, match="Untrusted"):
            await GitHubReleases("VardgesM/sunk", client).latest()


class FakeDeployment:
    def __init__(self, failure=None):
        self.failure, self.calls = failure, []

    def step(self, name):
        self.calls.append(name)
        if name == self.failure:
            raise RuntimeError("password=do-not-leak")

    def preserve_and_build(self, status):
        self.step("build")

    def stop(self, status):
        self.step("stop")

    def migrate(self, status):
        self.step("migrate")

    def start(self, status, *, previous=False):
        self.step("old_start" if previous else "start")

    def verify(self, status, *, previous=False):
        self.step("old_verify" if previous else "verify")


@pytest.mark.parametrize(
    "failure,changed,expected",
    [
        (None, False, "SUCCESS"),
        (None, True, "SUCCESS"),
        ("build", False, "FAILED"),
        ("verify", False, "ROLLED_BACK"),
        ("start", False, "ROLLED_BACK"),
        ("migrate", True, "FAILED"),
        ("verify", True, "FAILED"),
    ],
)
def test_install_and_rollback_policy(failure, changed, expected, release_files, tmp_path, caplog):
    store = UpdateStore(tmp_path / "journal")
    status = job(store, release_files[2])
    if changed:
        status.release.manifest.migration_revision = "0015_test"
    deployment = FakeDeployment(failure)
    install(store, status, deployment)
    saved = store.read()
    assert saved.state == expected
    assert "do-not-leak" not in caplog.text + saved.model_dump_json()
    if changed and failure:
        assert saved.recovery_required
        assert "old_start" not in deployment.calls
    elif expected == "ROLLED_BACK":
        assert deployment.calls[-2:] == ["old_start", "old_verify"]
    if failure == "build":
        assert "stop" not in deployment.calls


@pytest.mark.parametrize("migration", [False, True])
def test_restart_never_replays_installation(migration, release_files, tmp_path):
    store = UpdateStore(tmp_path / "journal")
    status = job(store, release_files[2])
    store.write(status, state="VERIFYING", services_stopped=True, migration_started=migration)
    deployment = FakeDeployment()
    interrupted(UpdateStore(store.root), store.read(), deployment)
    assert "build" not in deployment.calls and "migrate" not in deployment.calls
    assert store.read().state == ("FAILED" if migration else "ROLLED_BACK")


def test_interrupted_check_never_rolls_back_previous_success(release_files, tmp_path):
    store = UpdateStore(tmp_path)
    status = job(store, release_files[2])
    store.write(status, state="CHECKING", services_stopped=True)
    deployment = FakeDeployment()
    interrupted(store, status, deployment)
    assert not deployment.calls


@pytest.mark.anyio
async def test_preparation_backup_failure_prevents_handoff(
    release_files, tmp_path, monkeypatch, caplog
):
    _, archive, release = release_files
    settings = Settings(
        _env_file=None,
        postgres_password="database-secret",
        update_directory=str(tmp_path / "journal"),
        backup_directory=str(tmp_path / "backups"),
    )
    store = UpdateStore(settings.update_directory)
    status = job(store, release)

    async def download(self, release, path):
        path.write_bytes(archive.read_bytes())

    monkeypatch.setattr(GitHubReleases, "download", download)
    monkeypatch.setattr(prepare, "disk_space", lambda *_: None)

    class Database:
        @asynccontextmanager
        async def sessions(self):
            raise RuntimeError("database-secret")
            yield

        async def close(self):
            pass

    monkeypatch.setattr(prepare, "Database", lambda _: Database())
    await prepare.prepare(settings, status, "backup-secret-password")
    assert store.read().state == "FAILED"
    assert store.read().failure_stage == "BACKING_UP"
    assert "secret" not in store.read().model_dump_json() + caplog.text


@pytest.mark.anyio
async def test_preparation_creates_encrypted_pinned_backup(release_files, tmp_path, monkeypatch):
    _, archive, release = release_files
    settings = Settings(
        _env_file=None,
        postgres_password="db-secret",
        update_directory=str(tmp_path / "journal"),
        backup_directory=str(tmp_path / "backups"),
    )
    store = UpdateStore(settings.update_directory)
    status = job(store, release)

    async def download(self, release, path):
        path.write_bytes(archive.read_bytes())

    monkeypatch.setattr(GitHubReleases, "download", download)
    monkeypatch.setattr(prepare, "disk_space", lambda *_: None)
    monkeypatch.setattr(
        "app.services.backup_store.dump",
        lambda settings, path, snapshot: path.write_bytes(b"test-pg-dump"),
    )
    session = SimpleNamespace(
        execute=AsyncMock(),
        scalar=AsyncMock(side_effect=["0014_backups", 170000, "test-snapshot"]),
        commit=AsyncMock(),
    )

    class Database:
        @asynccontextmanager
        async def sessions(self):
            yield session

        async def close(self):
            pass

    monkeypatch.setattr(prepare, "Database", lambda _: Database())
    await prepare.prepare(settings, status, "saved-outside-the-db")
    saved = store.read()
    assert saved.state == "READY" and saved.backup_id
    recovery = store.job(saved.job_id) / "recovery.mmbak"
    assert recovery.read_bytes().startswith(b"MMBACKUP")
    assert b"test-pg-dump" not in recovery.read_bytes()
    assert "saved-outside-the-db" not in (store.root / "status.json").read_text()
    # Deleting the normal backup cannot delete the updater's pinned recovery copy.
    prepare.BackupStore(settings).delete(saved.backup_id)
    assert recovery.is_file()


@pytest.fixture
def updater_api(api, tmp_path):
    settings = api._transport.app.state.settings
    settings.update_directory = str(tmp_path / "updates")
    return api


@pytest.mark.anyio
async def test_update_api_check_status_and_install(
    updater_api, database_sessions, release_files, monkeypatch
):
    api = updater_api
    settings = api._transport.app.state.settings
    settings.application_mode, settings.update_enabled = "cloud", True
    monkeypatch.setattr(GitHubReleases, "latest", AsyncMock(return_value=release_files[2]))
    response = await api.post("/api/system/updates/check")
    assert response.status_code == 200 and response.json()["available"]
    store = UpdateStore(settings.update_directory)
    atomic_json(
        store.root / "runner.json",
        {"handler": "cloud-compose-v1", "heartbeat": datetime.now(UTC).isoformat()},
    )
    prepared = AsyncMock()
    monkeypatch.setattr("app.api.updates.prepare", prepared)
    response = await api.post(
        "/api/system/updates/install",
        json={"version": "1.2.0", "confirmation": "UPDATE", "passphrase": "not-logged-secret"},
    )
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "DOWNLOADING"
    assert "not-logged-secret" not in response.text
    prepared.assert_awaited_once()
    assert (await api.post("/api/system/updates/check")).status_code == 409
    async with database_sessions() as session:
        rows = list(await session.scalars(select(AuditLog).where(AuditLog.entity_type == "system")))
        assert any("updates/install" in row.summary for row in rows)
        assert "not-logged-secret" not in str([row.summary for row in rows])


@pytest.mark.anyio
async def test_no_update_and_unsupported_topology(updater_api, monkeypatch):
    monkeypatch.setattr(GitHubReleases, "latest", AsyncMock(return_value=None))
    result = await updater_api.post("/api/system/updates/check")
    assert result.json()["state"] == "IDLE" and not result.json()["available"]
    assert not result.json()["install_supported"]
    result = await updater_api.post(
        "/api/system/updates/install",
        json={"version": "1.2.0", "confirmation": "UPDATE", "passphrase": "not-logged-secret"},
    )
    assert result.status_code == 409


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["OPERATOR", "VIEWER"])
async def test_admin_and_csrf(updater_api, role):
    from tests.test_auth import account, sign_in

    api = updater_api
    assert (
        await api.post("/api/system/updates/check", headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    await account(api, role)
    await sign_in(api, "reader", "another-test-password")
    for path in ("status", "check", "install"):
        response = await (
            api.get(f"/api/system/updates/{path}")
            if path == "status"
            else api.post(f"/api/system/updates/{path}", json={})
        )
        assert response.status_code == 403


@pytest.mark.anyio
async def test_updater_requires_login(updater_api):
    updater_api.cookies.clear()
    assert (await updater_api.get("/api/system/updates/status")).status_code == 401


def test_stale_runner_is_not_reported_online(tmp_path):
    store = UpdateStore(tmp_path)
    atomic_json(
        store.root / "runner.json",
        {
            "handler": "cloud-compose-v1",
            "heartbeat": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert not store.runner_alive()


def test_old_ready_job_cannot_install_after_runner_returns(tmp_path, release_files, monkeypatch):
    import app.updater as runner

    config = HostConfig(
        handler="cloud-compose-v1",
        project_name="test",
        project_directory=tmp_path,
        compose_files=[tmp_path / "cloud.yml"],
        env_file=tmp_path / ".env",
        shared_directory=tmp_path / "shared",
        private_directory=tmp_path / "private",
    )
    store = UpdateStore(config.shared_directory)
    status = job(store, release_files[2])
    status.updated_at = datetime.now(UTC) - timedelta(hours=1)
    atomic_json(store.root / "status.json", status.model_dump(mode="json"))
    deployment = FakeDeployment()
    monkeypatch.setattr(runner, "CloudCompose", lambda *args: deployment)
    runner.run(config, once=True)
    assert store.read().state == "FAILED" and store.read().failure_stage == "READY"
    assert not deployment.calls


def test_deployment_fixed_arguments_and_preserves_data(tmp_path, release_files, monkeypatch):
    environment = tmp_path / ".env.cloud"
    environment.write_text("MODBUS_WRITES_ENABLED=false\nPRIVATE_TOKEN=unchanged\n")
    compose = tmp_path / "cloud.yml"
    compose.write_text("# pinned topology")
    config = HostConfig(
        handler="cloud-compose-v1",
        project_name="isolated-test",
        project_directory=tmp_path,
        compose_files=[compose],
        env_file=environment,
        shared_directory=tmp_path / "shared",
        private_directory=tmp_path / "private",
    )
    store = UpdateStore(config.shared_directory)
    status = job(store, release_files[2])
    deployment = CloudCompose(config, store)
    work = deployment.work(status)
    atomic_json(
        work / "deployment.json",
        {
            "fingerprint": deployment.fingerprint(),
            "probe": {
                "version": APP_VERSION,
                "revision": "0014_backups",
                "mode": "cloud",
                "writes_enabled": False,
            },
        },
    )
    called = []
    monkeypatch.setattr(deployment, "run", lambda args, **kw: called.append(args) or "")
    before = environment.read_bytes()
    deployment.stop(status)
    deployment.start(status)
    assert environment.read_bytes() == before
    assert all("--env-file" in args for args in called if args[1] == "compose")
    assert not any(
        part in {"down", "prune", "worker", "sync", "postgres", "-v"}
        for args in called
        for part in args
    )
    assert called[-1][-2:] == ["api", "frontend"]
    environment.write_text("MODBUS_WRITES_ENABLED=true")
    with pytest.raises(UpdateError, match="changed"):
        deployment.start(status)


@pytest.mark.anyio
async def test_controlled_recovery_reuses_phase12_and_never_changes_write_setting(
    tmp_path, release_files, monkeypatch
):
    import app.update_recovery as recovery

    settings = Settings(
        _env_file=None,
        postgres_password="test-db-secret",
        update_directory=str(tmp_path / "journal"),
        backup_directory=str(tmp_path / "backups"),
    )
    store = UpdateStore(settings.update_directory)
    status = job(store, release_files[2])
    encrypted = store.job(status.job_id) / "recovery.mmbak"
    encrypted.write_bytes(b"test-encrypted-backup")
    store.write(
        status, state="FAILED", recovery_required=True, backup_sha256=artifact.sha256(encrypted)
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=170000))

    class Database:
        @asynccontextmanager
        async def sessions(self):
            yield session

        async def close(self):
            pass

    monkeypatch.setattr(recovery, "Database", lambda _: Database())
    validated = []

    def validate(artifacts, identifier, password, major):
        assert password == "external-password" and major == 17
        validated.append(identifier)
        info = artifacts.read(identifier)
        info.status = "VALIDATED"
        artifacts.write(info)

    monkeypatch.setattr(recovery.BackupStore, "validate", validate)
    staged_restore = AsyncMock(return_value="mm_previous_test")
    monkeypatch.setattr(recovery, "restore", staged_restore)
    assert (
        await recovery.recover(settings, status.job_id, "external-password") == "mm_previous_test"
    )
    assert len(validated) == 1
    staged_restore.assert_awaited_once_with(settings, validated[0], "external-password")
    assert (
        store.read().recovery_required
    )  # Verification and sync reconciliation are still explicit.
    assert "external-password" not in store.read().model_dump_json()
    assert not settings.modbus_writes_enabled
    settings.modbus_writes_enabled = True
    with pytest.raises(UpdateError, match="writes disabled"):
        await recovery.recover(settings, status.job_id, "external-password")
    assert settings.modbus_writes_enabled is True


@pytest.mark.anyio
async def test_corrupt_pinned_backup_never_reaches_restore(tmp_path, release_files, monkeypatch):
    import app.update_recovery as recovery

    settings = Settings(_env_file=None, postgres_password="test", update_directory=str(tmp_path))
    store = UpdateStore(tmp_path)
    status = job(store, release_files[2])
    (store.job(status.job_id) / "recovery.mmbak").write_bytes(b"damaged")
    store.write(status, recovery_required=True, backup_sha256="0" * 64)
    staged_restore = AsyncMock()
    monkeypatch.setattr(recovery, "restore", staged_restore)
    with pytest.raises(UpdateError, match="integrity"):
        await recovery.recover(settings, status.job_id, "external-password")
    staged_restore.assert_not_awaited()
