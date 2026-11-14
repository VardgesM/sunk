"""Disposable PostgreSQL schemas only; simulator control, never physical hardware.

Run with the existing isolated TEST_DATABASE_URL harness. No database daemon is started here.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from app.models import AlarmEvent, Command, Device, SyncMapping, Tag, TagHistory
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from tests.test_alarms import engine as alarm_engine
from tests.test_alarms import rule as alarm_rule
from tests.test_automation import engine as automation_engine
from tests.test_automation import fixtures, rule_payload, sample
from tests.test_commands import enqueue, prepare, processor
from tests.test_configuration import create
from tests.test_dashboards import dashboard, widget
from tests.test_sync import (
    drain,
    numeric_tag,
    pair,  # noqa: F401 -- shared disposable-schema fixture
)

pytestmark = pytest.mark.anyio


def migrate(connection, revision, *, downgrade=False):
    config = Config("server/alembic.ini")
    config.attributes["connection"] = connection
    (command.downgrade if downgrade else command.upgrade)(config, revision)


async def test_deletion_waits_for_command_and_progress_does_not_deadlock(pair):  # noqa: F811
    edge, _cloud, _client, _identity = pair
    tag = await prepare(edge.api, edge.sessions)
    command = await enqueue(edge.api, tag, 12)
    proc = processor(edge.sessions)
    assert await proc.claim() == command["id"]
    verifying, resume = asyncio.Event(), asyncio.Event()
    original = proc.transition

    async def transition(identifier, status, **kwargs):
        if status == "VERIFYING":
            verifying.set()
            await resume.wait()
        await original(identifier, status, **kwargs)

    proc.transition = transition
    processing = asyncio.create_task(proc.process(command["id"]))
    deletion = None
    try:
        async with asyncio.timeout(10):
            await verifying.wait()
            deletion = asyncio.create_task(edge.api.delete(f"/api/tags/{tag['id']}"))
            async with edge.sessions() as session:
                # Wait for the actual database lock wait, rather than guessing a delay.
                while not await session.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                        "AND objid=927013 AND NOT granted)"
                    )
                ):
                    assert not deletion.done()
                    await asyncio.sleep(0.01)
            resume.set()
            await processing
            assert (await deletion).status_code == 204
        result = (await edge.api.get(f"/api/commands/{command['id']}")).json()
        assert result["status"] == "SUCCESS"
        assert (await edge.api.get(f"/api/tags/{tag['id']}/value")).status_code == 404
    finally:
        resume.set()
        tasks = [processing, *([deletion] if deletion else [])]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_archive_connection_graph_sync_retains_evidence(pair):  # noqa: F811
    edge, cloud, client, _identity = pair
    sensor, _other, relay = await fixtures(edge.api, edge.sessions)
    response = await edge.api.patch(
        f"/api/tags/{sensor['id']}", json={"history_enabled": True}
    )
    assert response.status_code == 200
    await create(edge.api, "automation/rules", **rule_payload(sensor, relay))
    await alarm_rule(edge.api, sensor)
    board = await dashboard(edge.api)
    await create(
        edge.api, f"dashboards/{board['id']}/widgets", **widget([sensor["id"]])
    )
    now = datetime.now(UTC)
    await sample(edge.sessions, sensor, 40, now)
    await sample(edge.sessions, relay, False, now)
    await automation_engine(edge.sessions).tick(now)
    await alarm_engine(edge.sessions).tick(now)
    async with edge.sessions() as session:
        pending = await session.scalar(select(Command))
        assert pending and pending.status == "QUEUED"
        device = await session.get(Device, sensor["device_id"])
        connection_id = device.connection_id
    await drain(client, edge)
    assert (await cloud.api.get("/api/alarms/summary")).json()["active"] == 1
    assert (
        await edge.api.delete(f"/api/connections/{connection_id}")
    ).status_code == 204
    await drain(client, edge)
    # Both installations hide active configuration but keep forensic references intact.
    for node in (edge, cloud):
        for resource in (
            "connections",
            "devices",
            "tags",
            "automation/rules",
            "alarms/rules",
        ):
            assert (await node.api.get(f"/api/{resource}")).json() == []
            archived = (await node.api.get(f"/api/{resource}?archived=true")).json()
            assert archived and all(row["archived_at"] for row in archived)
        assert (await node.api.get("/api/tags/values")).json() == []
        assert (await node.api.get("/api/commands")).json()[0]["status"] == "CANCELLED"
        async with node.sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(TagHistory)) == 1
            )
            event = await session.scalar(select(AlarmEvent))
            assert (
                event.state == "CLEARED"
                and event.clear_reason == "Configuration deleted"
            )
        boards = (await node.api.get("/api/dashboards")).json()
        detail = (await node.api.get(f"/api/dashboards/{boards[0]['id']}")).json()
        assert detail["widgets"] == []


async def test_archive_migration_preserves_rows_and_backfills_legacy_cloud_tombstone(
    pair,  # noqa: F811
):
    edge, cloud, client, _identity = pair
    tag = await numeric_tag(edge, history_enabled=True)
    await sample(edge.sessions, tag, 25, datetime.now(UTC))
    await drain(client, edge)
    engine = cloud.sessions.kw["bind"]
    async with cloud.sessions() as session, session.begin():
        mapping = await session.scalar(
            select(SyncMapping).where(SyncMapping.entity == "tags")
        )
        mapping.deleted = (
            True  # The marker used by the pre-archive Cloud implementation.
        )
        tag_id = mapping.cloud_id
        await session.execute(update(Tag).where(Tag.id == tag_id).values(enabled=False))
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: migrate(c, "0014_backups", downgrade=True))
        before = (
            await connection.execute(
                text("SELECT id, tag_id, value_numeric FROM tag_history")
            )
        ).all()
        await connection.run_sync(lambda c: migrate(c, "head"))
        after = (
            await connection.execute(
                text("SELECT id, tag_id, value_numeric FROM tag_history")
            )
        ).all()
        assert before == after and len(after) == 1
    async with cloud.sessions() as session:
        retained = await session.get(Tag, tag_id)
        assert retained.archived_at is not None and not retained.enabled
    assert (await cloud.api.get("/api/tags")).json() == []


@pytest.mark.parametrize("reuse", ["tag_key", "slave_id"])
async def test_downgrade_refuses_reused_identifiers_without_losing_data(pair, reuse):  # noqa: F811
    edge, _cloud, _client, _identity = pair
    tag = await numeric_tag(edge)
    if reuse == "tag_key":
        assert (await edge.api.delete(f"/api/tags/{tag['id']}")).status_code == 204
        await create(
            edge.api,
            "tags",
            name="Replacement",
            key=tag["key"],
            device_id=tag["device_id"],
            register_type="holding_register",
            address=0,
            data_type="uint16",
        )
        model = Tag
    else:
        device = (await edge.api.get(f"/api/devices/{tag['device_id']}")).json()
        assert (
            await edge.api.delete(f"/api/devices/{device['id']}")
        ).status_code == 204
        await create(
            edge.api,
            "devices",
            name="Replacement",
            connection_id=device["connection_id"],
            slave_id=device["slave_id"],
        )
        model = Device
    engine = edge.sessions.kw["bind"]
    with pytest.raises(DBAPIError, match="archived identifiers have been reused"):
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda c: migrate(c, "0014_backups", downgrade=True)
            )
    async with edge.sessions() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version"))
            == "0015_configuration_archive"
        )
        assert await session.scalar(select(func.count()).select_from(model)) == 2
