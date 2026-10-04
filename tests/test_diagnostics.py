"""On-demand diagnostics: existing state only, without hardware or production resources."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.core.version import APP_VERSION
from app.models import EdgeInstallation, RecoveryState, SyncOutbox, SyncState, TagCurrentValue, User
from app.schemas.backup import BackupInfo
from app.services import diagnostics
from tests.test_configuration import setup_tag
from tests.test_system_info import seed_revisions

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def local_environment(api, tmp_path, monkeypatch):
    api._transport.app.state.settings.backup_directory = str(tmp_path / "backups")
    api._transport.app.state.started_monotonic = 100.0
    monkeypatch.setattr(diagnostics, "monotonic", lambda: 200.0)
    monkeypatch.setattr(diagnostics.socket, "gethostname", lambda: "api-test-container")

    class FixedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(diagnostics, "datetime", FixedTime)


async def read(api):
    response = await api.get("/api/system/diagnostics")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("role", ["ADMIN", "OPERATOR", "VIEWER"])
async def test_metadata_access_unknowns_and_no_directory_creation(api, database_sessions, role):
    async with database_sessions.begin() as session:
        await session.execute(update(User).values(role=role))
    await seed_revisions(database_sessions, ["0013_realtime_sync"])
    value = await read(api)
    assert value["application_version"] == APP_VERSION
    assert value["application_mode"] == "standalone"
    assert value["database_revision"] == "0013_realtime_sync"
    assert value["database_status"] == "OK" and value["database_latency_ms"] >= 0
    assert value["sync_status"] == "DISABLED" and value["pending_sync_count"] is None
    assert value["telemetry_status"] == "UNKNOWN" and value["last_telemetry_at"] is None
    assert value["backup_status"] == "NONE" and value["last_backup_at"] is None
    assert value["disk_free_bytes"] is None
    assert value["hostname"] == "api-test-container" and value["uptime_seconds"] == 100
    assert not Path(api._transport.app.state.settings.backup_directory).exists()
    api.cookies.clear()
    assert (await api.get("/api/system/diagnostics")).status_code == 401


@pytest.mark.parametrize(
    "quality,age,expected",
    [
        ("GOOD", 8, "FRESH"),
        ("GOOD", 31, "STALE"),
        ("STALE", 1, "STALE"),
        ("COMM_ERROR", 1, "UNAVAILABLE"),
        ("BAD", 1, "UNAVAILABLE"),
        ("DISABLED", 1, "UNAVAILABLE"),
        ("GOOD", -5, "UNKNOWN"),
    ],
)
async def test_freshness_uses_success_timestamp_quality_and_poll_interval(
    api,
    database_sessions,
    quality,
    age,
    expected,
):
    tag = await setup_tag(api, poll_interval_ms=10000)
    stamp = NOW - timedelta(seconds=age)
    async with database_sessions.begin() as session:
        session.add(
            TagCurrentValue(
                tag_id=tag["id"],
                quality=quality,
                value_numeric=12,
                source="modbus_tcp",
                source_timestamp=stamp,
                updated_at=NOW,
            )
        )
    value = await read(api)
    assert value["telemetry_status"] == expected
    assert value["last_telemetry_at"] == stamp.isoformat()
    async with database_sessions() as session:
        current = await session.get(TagCurrentValue, tag["id"])
        assert current.quality == quality and current.revision == 1
        assert await session.scalar(select(func.count()).select_from(SyncOutbox)) == 0


async def test_partial_telemetry_and_disabled_configuration(api, database_sessions):
    tag = await setup_tag(api, poll_interval_ms=10000)
    other = await api.post(
        "/api/tags",
        json={
            "name": "No samples",
            "key": "missing_sample",
            "device_id": tag["device_id"],
            "register_type": "holding_register",
            "address": 20,
            "data_type": "uint16",
        },
    )
    assert other.status_code == 201
    async with database_sessions.begin() as session:
        session.add(
            TagCurrentValue(
                tag_id=tag["id"],
                quality="GOOD",
                value_numeric=12,
                source="simulator",
                source_timestamp=NOW,
            )
        )
    assert (await read(api))["telemetry_status"] == "DEGRADED"
    await api.patch(f"/api/tags/{other.json()['id']}", json={"enabled": False})
    assert (await read(api))["telemetry_status"] == "FRESH"
    await api.patch(f"/api/devices/{tag['device_id']}", json={"enabled": False})
    assert (await read(api))["telemetry_status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "error,seconds,expected",
    [
        (None, 3, "CONNECTED"),
        (None, 60, "DISCONNECTED"),
        ("private-token-do-not-return", 3, "UNAVAILABLE"),
    ],
)
async def test_edge_sync_uses_persisted_state_without_secrets(
    api,
    database_sessions,
    error,
    seconds,
    expected,
):
    api._transport.app.state.settings.application_mode = "edge"
    stamp = NOW - timedelta(seconds=seconds)
    async with database_sessions.begin() as session:
        session.add(SyncState(id=1, mode="edge", last_sync_at=stamp, last_error=error))
        session.add(
            SyncOutbox(
                entity="tag_history",
                operation="upsert",
                priority=10,
                payload={"private": "secret-payload"},
            )
        )
    value = await read(api)
    assert value["sync_status"] == expected and value["pending_sync_count"] == 1
    assert value["last_sync_at"] == stamp.isoformat()
    assert "secret" not in str(value) and "private" not in str(value)


@pytest.mark.parametrize("mode", ["edge", "cloud"])
async def test_restore_pause_is_visible(api, database_sessions, mode):
    api._transport.app.state.settings.application_mode = mode
    async with database_sessions.begin() as session:
        session.add(
            RecoveryState(id=1, backup_id=str(uuid4()), restored_at=NOW, sync_review_required=True)
        )
    assert (await read(api))["sync_status"] == "PAUSED"


@pytest.mark.parametrize(
    "ages,expected",
    [
        ([], "UNKNOWN"),
        ([3, 8], "CONNECTED"),
        ([3, 60], "DEGRADED"),
        ([60], "DISCONNECTED"),
    ],
)
async def test_cloud_heartbeats_do_not_invent_edge_queue_or_success_time(
    api,
    database_sessions,
    ages,
    expected,
):
    api._transport.app.state.settings.application_mode = "cloud"
    async with database_sessions.begin() as session:
        for age in ages:
            session.add(
                EdgeInstallation(
                    id=str(uuid4()),
                    name="Test installation",
                    token_hash="sensitive-machine-digest",
                    enabled=True,
                    last_seen_at=NOW - timedelta(seconds=age),
                )
            )
    value = await read(api)
    assert value["sync_status"] == expected
    assert value["last_sync_at"] is None and value["pending_sync_count"] is None
    assert "sensitive" not in str(value)


def artifact(directory, status, *, kind="backup", age=0):
    directory.mkdir(exist_ok=True)
    row = BackupInfo(
        id=uuid4(), kind=kind, created_at=NOW - timedelta(days=age), size=42, status=status
    )
    (directory / f"{row.id}.json").write_text(row.model_dump_json(), encoding="utf-8")
    (directory / f"{row.id}.mmbak").write_bytes(b"test artifact; never restored")
    return row


async def test_backup_summary_ignores_uploads_and_keeps_last_success(api, monkeypatch):
    directory = Path(api._transport.app.state.settings.backup_directory)
    artifact(directory, "AVAILABLE", age=1)
    artifact(directory, "FAILED")
    artifact(directory, "VALIDATED", kind="upload")
    monkeypatch.setattr(
        diagnostics.shutil, "disk_usage", lambda _: SimpleNamespace(free=71 * 1024**3)
    )
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    value = await read(api)
    assert value["backup_status"] == "FAILED"
    assert value["last_backup_at"] == (NOW - timedelta(days=1)).isoformat()
    assert value["disk_free_bytes"] == 71 * 1024**3
    assert str(directory) not in str(value)
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


@pytest.mark.parametrize(
    "status,expected", [("CREATING", "IN_PROGRESS"), ("AVAILABLE", "AVAILABLE")]
)
async def test_backup_status(api, status, expected):
    artifact(Path(api._transport.app.state.settings.backup_directory), status)
    assert (await read(api))["backup_status"] == expected


async def test_missing_archive_corrupt_metadata_and_host_failures(api, monkeypatch, caplog):
    directory = Path(api._transport.app.state.settings.backup_directory)
    row = artifact(directory, "AVAILABLE")
    (directory / f"{row.id}.mmbak").unlink()
    assert (await read(api))["backup_status"] == "UNKNOWN"
    (directory / f"{row.id}.json").write_text("private-token-secret-not-json")
    for name in ("gethostname",):
        monkeypatch.setattr(
            diagnostics.socket, name, Mock(side_effect=OSError("private-host-path"))
        )
    monkeypatch.setattr(
        diagnostics.shutil, "disk_usage", Mock(side_effect=OSError("private-disk-path"))
    )
    value = await read(api)
    assert value["backup_status"] == "UNKNOWN"
    assert value["disk_free_bytes"] is None and value["hostname"] is None
    assert "private-" not in str(value) and "private-" not in caplog.text


async def test_database_probe_failure_is_partial_and_sanitized(api, caplog):
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=OperationalError("private-query", {}, Exception("secret"))),
        rollback=AsyncMock(),
    )
    value = await diagnostics.collect(session, api._transport.app.state.settings, None)
    assert value.database_status == "ERROR" and value.database_latency_ms is None
    assert value.database_revision is None and value.telemetry_status == "UNKNOWN"
    assert value.uptime_seconds is None
    assert value.hostname == "api-test-container"
    assert "private-query" not in caplog.text and "secret" not in caplog.text
