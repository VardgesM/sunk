"""Operational deletion preserves evidence and never performs a physical action."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.models import (
    AlarmEvent,
    AutomationRule,
    Connection,
    Device,
    EdgeInstallation,
    NotificationDelivery,
    Tag,
    TagCurrentValue,
    TagHistory,
)
from app.schemas.telemetry import utc
from app.services.archive import archive_configuration
from app.services.configuration_transfer import export_configuration
from app.services.current_values import Reading
from app.sync.catalog import columns
from app.sync.mirror import apply_event, identity, local_key, values
from app.sync.protocol import Event
from app.worker.polling import collect_one, load_configuration
from app.worker.simulator import SimulatorSource
from app.worker.sources import CommunicationError
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tests.test_alarms import engine as alarm_engine
from tests.test_alarms import rule as alarm_rule
from tests.test_automation import commands, engine, fixtures, rule_payload, sample
from tests.test_commands import enqueue, prepare, processor
from tests.test_configuration import create, setup_tag
from tests.test_dashboards import dashboard, widget

pytestmark = pytest.mark.anyio


async def test_archive_tag_keeps_history_removes_current_and_frees_key(
    api, database_sessions
):
    tag = await setup_tag(api, history_enabled=True)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 42, now)
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    assert (await api.get("/api/tags")).json() == []
    archived = (await api.get("/api/tags?archived=true")).json()
    assert archived[0]["archived_at"] and not archived[0]["enabled"]
    assert (await api.get("/api/tags/values")).json() == []
    assert (
        await api.patch(f"/api/tags/{tag['id']}", json={"enabled": True})
    ).status_code == 404
    history = await api.get(
        f"/api/tags/{tag['id']}/history",
        params={
            "from": (now - timedelta(seconds=1)).isoformat(),
            "to": (now + timedelta(seconds=1)).isoformat(),
        },
    )
    assert history.status_code == 200, history.text
    assert history.json()["count"] == 1
    async with database_sessions() as session:
        assert await session.get(TagCurrentValue, tag["id"]) is None
        assert await session.scalar(select(func.count()).select_from(TagHistory)) == 1
        document = await export_configuration(session)
        assert document.data.tags == []
    replacement = await create(
        api,
        "tags",
        name=tag["name"],
        key=tag["key"],
        device_id=tag["device_id"],
        register_type="holding_register",
        address=0,
        data_type="uint16",
    )
    assert replacement["id"] != tag["id"]
    assert len((await api.get("/api/tags")).json()) == 1


@pytest.mark.parametrize("entity", ["tags", "devices", "connections"])
async def test_archive_stops_work_cancels_queued_and_preserves_command(
    api, database_sessions, entity
):
    tag = await prepare(api, database_sessions)
    queued = await enqueue(api, tag, 12)
    async with database_sessions() as session:
        cached = (await load_configuration(session))[0]
        device = await session.get(Device, tag["device_id"])
        identifier = {
            "tags": tag["id"],
            "devices": device.id,
            "connections": device.connection_id,
        }[entity]
    assert (await api.delete(f"/api/{entity}/{identifier}")).status_code == 204
    assert (await api.get(f"/api/commands/{queued['id']}")).json()[
        "status"
    ] == "CANCELLED"
    assert (
        await api.post(f"/api/tags/{tag['id']}/commands", json={"value": 3})
    ).status_code == 422
    source = SimulatorSource()
    source.set_control = Mock(wraps=source.set_control)
    proc = processor(database_sessions, source=source)
    assert await proc.claim() is None
    await proc.process(queued["id"])
    source.set_control.assert_not_called()
    # An already collected sample cannot resurrect a deleted current value.
    async with database_sessions() as session, session.begin():
        assert await load_configuration(session) == []
        await collect_one(
            session,
            source,
            cached,
            acquired=Reading(Decimal(14), datetime.now(UTC), source="simulator"),
        )
        assert await session.get(TagCurrentValue, tag["id"]) is None


async def test_claimed_but_unstarted_command_cannot_write_after_archive(
    api, database_sessions
):
    tag = await prepare(api, database_sessions)
    queued = await enqueue(api, tag, 12)
    source = SimulatorSource()
    source.set_control = Mock(wraps=source.set_control)
    proc = processor(database_sessions, source=source)
    assert await proc.claim() == queued["id"]
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    await proc.process(queued["id"])
    result = (await api.get(f"/api/commands/{queued['id']}")).json()
    assert result["status"] == "FAILED"
    source.set_control.assert_not_called()


async def test_archive_input_retires_whole_rule_cancels_other_output_and_keeps_execution(
    api, database_sessions
):
    sensor, _, relay = await fixtures(api, database_sessions)
    rule = await create(api, "automation/rules", **rule_payload(sensor, relay))
    now = datetime.now(UTC)
    await sample(database_sessions, sensor, 40, now)
    worker = engine(database_sessions)
    await worker.tick(now)
    assert len(await commands(database_sessions)) == 1
    assert (await api.delete(f"/api/tags/{sensor['id']}")).status_code == 204
    assert (await api.get("/api/automation/rules")).json() == []
    assert (await api.get(f"/api/tags/{relay['id']}")).status_code == 200
    assert (await commands(database_sessions))[0].status == "CANCELLED"
    await worker.tick(now + timedelta(seconds=1))
    assert len(await commands(database_sessions)) == 1
    assert (await api.get(f"/api/automation/rules/{rule['id']}/executions")).json()
    assert (
        await api.patch(f"/api/automation/rules/{rule['id']}", json={"enabled": True})
    ).status_code == 404
    assert (
        await api.post("/api/automation/rules", json=rule_payload(sensor, relay))
    ).status_code == 422


async def test_archive_closes_open_alarm_honestly_and_retains_event(
    api, database_sessions
):
    tag = await setup_tag(api)
    rule = await alarm_rule(api, tag, notification_enabled=True)
    now = datetime.now(UTC)
    await sample(database_sessions, tag, 40, now)
    worker = alarm_engine(database_sessions)
    await worker.tick(now)
    assert (await api.get("/api/alarms/summary")).json()["active"] == 1
    assert (await api.delete(f"/api/alarms/rules/{rule['id']}")).status_code == 204
    assert (await api.get("/api/alarms/summary")).json()["active"] == 0
    event = (await api.get("/api/alarms/events")).json()[0]
    assert (
        event["state"] == "CLEARED" and event["clear_reason"] == "Configuration deleted"
    )
    assert (
        await api.post(f"/api/alarms/events/{event['id']}/acknowledge")
    ).status_code == 409
    await worker.tick(now + timedelta(seconds=1))
    async with database_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AlarmEvent)) == 1
        assert (await session.scalar(select(NotificationDelivery))).status == "SKIPPED"


async def test_device_slave_reuse_and_archived_references_rejected(
    api, database_sessions
):
    tag = await setup_tag(api)
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    assert (await api.delete(f"/api/devices/{device['id']}")).status_code == 204
    new = await create(
        api,
        "devices",
        name=device["name"],
        connection_id=device["connection_id"],
        slave_id=device["slave_id"],
    )
    assert new["id"] != device["id"]
    payload = {
        "name": "Another",
        "key": "another",
        "device_id": device["id"],
        "register_type": "coil",
        "data_type": "bool",
        "address": 0,
    }
    assert (await api.post("/api/tags", json=payload)).status_code == 422
    assert (
        await api.post(
            "/api/alarms/rules",
            json={
                "name": "Invalid",
                "tag_id": tag["id"],
                "operator": ">",
                "value": 3,
            },
        )
    ).status_code == 422


async def test_location_deletion_reparents_without_stopping_equipment(api):
    parent = await create(api, "locations", name="Root")
    folder = await create(api, "locations", name="Folder", parent_id=parent["id"])
    child = await create(api, "locations", name="Child", parent_id=folder["id"])
    tag = await setup_tag(api)
    await api.patch(
        f"/api/devices/{tag['device_id']}", json={"location_id": folder["id"]}
    )
    assert (await api.delete(f"/api/locations/{folder['id']}")).status_code == 204
    assert (await api.get(f"/api/locations/{child['id']}")).json()[
        "parent_id"
    ] == parent["id"]
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    assert device["location_id"] == parent["id"] and device["enabled"]
    assert (
        await api.post(
            "/api/locations", json={"name": "Invalid", "parent_id": folder["id"]}
        )
    ).status_code == 422


async def test_widgets_detach_without_broken_chart_or_export(api, database_sessions):
    tag = await setup_tag(api)
    other = await create(
        api,
        "tags",
        name="Other",
        key="other",
        device_id=tag["device_id"],
        register_type="input_register",
        address=1,
        data_type="uint16",
    )
    board = await dashboard(api)
    await create(api, f"dashboards/{board['id']}/widgets", **widget([tag["id"]]))
    chart = await create(
        api,
        f"dashboards/{board['id']}/widgets",
        **widget([tag["id"], other["id"]], type="chart"),
    )
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    detail = (await api.get(f"/api/dashboards/{board['id']}")).json()
    assert len(detail["widgets"]) == 1
    assert detail["widgets"][0]["id"] == chart["id"]
    assert detail["widgets"][0]["tag_ids"] == [other["id"]]
    async with database_sessions() as session:
        document = await export_configuration(session)
        assert len(document.data.tags) == 1 and len(document.data.widgets) == 1


async def test_archive_transaction_rollback_leaves_configuration_intact(
    api, database_sessions
):
    tag = await setup_tag(api)
    async with database_sessions() as session:
        await archive_configuration(session, Device, tag["device_id"])
        await session.rollback()
    assert (await api.get(f"/api/tags/{tag['id']}")).json()["enabled"]


@pytest.mark.parametrize("model", [Tag, Device, Connection, AutomationRule])
async def test_archived_cannot_be_enabled_in_database(api, database_sessions, model):
    sensor, _, relay = await fixtures(api, database_sessions)
    await create(api, "automation/rules", **rule_payload(sensor, relay))
    async with database_sessions() as session:
        row = await session.scalar(select(model))
        assert row is not None
        row.archived_at = datetime.now(UTC)
        row.enabled = True
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_legacy_sync_metadata_archive_ordering_and_delayed_current(
    api, database_sessions
):
    """Transport-independent mirror coverage; PG trigger/outbox tests remain separate."""
    from app.models import SyncMapping

    tag = await setup_tag(api, history_enabled=True)
    await sample(database_sessions, tag, 23, datetime.now(UTC))
    edge = EdgeInstallation(id=str(uuid4()), name="Test Edge", token_hash="x" * 64)
    events = []
    async with database_sessions() as session, session.begin():
        session.add(edge)
        for index, model in enumerate(
            (Connection, Device, Tag, TagCurrentValue, TagHistory), 1
        ):
            record = await session.scalar(select(model))
            payload = jsonable_encoder(
                {
                    column.name: getattr(record, column.name)
                    for column in columns(model.__tablename__)
                },
                custom_encoder={datetime: lambda value: utc(value).isoformat()},
            )
            payload.pop(
                "archived_at", None
            )  # Existing durable outbox before the upgrade.
            event = Event(
                event_id=uuid4(),
                sequence=index,
                entity=model.__tablename__,
                operation="upsert",
                payload=payload,
            )
            events.append(event)
            await apply_event(session, edge, event)
        key = identity(edge.id, "tags", local_key("tags", events[2].payload))
        cloud_tag_id = (await session.get(SyncMapping, key)).cloud_id
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
    async with database_sessions() as session, session.begin():
        record = await session.get(Tag, tag["id"])
        payload = jsonable_encoder(
            {column.name: getattr(record, column.name) for column in columns("tags")},
            custom_encoder={datetime: lambda value: utc(value).isoformat()},
        )
        archived = Event(
            event_id=uuid4(),
            sequence=10,
            entity="tags",
            operation="upsert",
            payload=payload,
        )
        await apply_event(session, edge, archived)
        # Old metadata and current state arrive after the archive. Neither may revive it.
        await apply_event(
            session, edge, events[2].model_copy(update={"event_id": uuid4()})
        )
        await apply_event(session, edge, events[3].model_copy(update={"sequence": 11}))
        await apply_event(session, edge, events[4])  # History retry remains idempotent.
    async with database_sessions() as session:
        retained = await session.get(Tag, cloud_tag_id)
        assert retained.archived_at is not None and not retained.enabled
        assert await session.get(TagCurrentValue, cloud_tag_id) is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(TagHistory)
                .where(TagHistory.tag_id == cloud_tag_id)
            )
            == 1
        )
    assert values("tags", events[2].payload)["archived_at"] is None
    with pytest.raises(ValueError, match="schema"):
        values("tags", {**events[2].payload, "unexpected": True})


@pytest.mark.parametrize("role", ["OPERATOR", "VIEWER"])
async def test_delete_still_requires_admin(api, role):
    from tests.test_auth import account, sign_in

    tag = await setup_tag(api)
    await account(api, role)
    await sign_in(api, "reader", "another-test-password")
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 403


async def test_cloud_cannot_archive_edge_configuration(api):
    tag = await setup_tag(api)
    api._transport.app.state.settings.application_mode = "cloud"
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409


async def test_archive_between_verification_attempts_reports_uncertainty_without_replay(
    api,
    database_sessions,
):
    tag = await prepare(api, database_sessions)
    queued = await enqueue(api, tag, 12)
    source = SimulatorSource()
    source.set_control = Mock(wraps=source.set_control)
    source.read = AsyncMock(
        side_effect=CommunicationError("Test read-back unavailable")
    )
    proc = processor(database_sessions, source=source)
    assert await proc.claim() == queued["id"]
    original = proc.transition

    async def transition(identifier, status, error=None, attempt=None):
        if status == "VERIFYING" and attempt == 2:
            assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204
        await original(identifier, status, error=error, attempt=attempt)

    proc.transition = transition
    await proc.process(queued["id"])
    result = (await api.get(f"/api/commands/{queued['id']}")).json()
    assert result["status"] == "FAILED"
    assert "Write may have occurred" in result["error_message"]
    assert "Not replayed" in result["error_message"]
    assert source.set_control.call_count == 1
    assert source.read.await_count == 1
