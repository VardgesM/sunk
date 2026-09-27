"""Real PostgreSQL outbox/mirror tests in disposable schemas; no physical/Telegram I/O."""

import asyncio
import os
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app
from app.models import Command, RemoteInbox, RemoteRequest, SyncOutbox, TagHistory
from app.services.current_values import Reading, upsert_current
from app.sync.client import SyncClient
from app.sync.protocol import Batch, RemoteAction
from app.sync.remote import accept_remote
from app.sync.state import initialize
from app.worker.commands import CommandProcessor
from app.worker.simulator import SimulatorSource
from tests.auth_helpers import login_test_admin
from tests.test_configuration import setup_tag
from tests.test_runtime import worker

pytestmark = pytest.mark.anyio
TOKEN = "isolated-machine-test-token-32-characters"


@pytest.fixture
async def pair():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL required")
    url = os.environ["TEST_DATABASE_URL"]
    admin = create_async_engine(url, hide_parameters=True)
    engines = []
    schemas = []
    nodes = []
    identity = str(uuid4())
    async with AsyncExitStack() as stack:
        try:
            for mode in ("edge", "cloud"):
                schema = "sync_test_" + uuid4().hex
                schemas.append(schema)
                async with admin.begin() as c:
                    await c.execute(CreateSchema(schema))
                engine = create_async_engine(
                    url,
                    hide_parameters=True,
                    connect_args={"server_settings": {"search_path": schema}},
                )
                engines.append(engine)

                def migrate(c):
                    cfg = Config("server/alembic.ini")
                    cfg.attributes["connection"] = c
                    command.upgrade(cfg, "head")

                async with engine.begin() as c:
                    await c.run_sync(migrate)
                sessions = async_sessionmaker(engine, expire_on_commit=False)
                settings = Settings(
                    postgres_password="test",
                    application_mode=mode,
                    edge_installation_id=identity if mode == "edge" else None,
                    telemetry_source="simulator" if mode == "edge" else "disabled",
                    simulator_enabled=False,
                    sync_cloud_url="http://cloud",
                    sync_allow_insecure_http=True,
                    sync_token=TOKEN,
                    sync_batch_size=500,
                )
                db = SimpleNamespace(sessions=sessions)
                await initialize(db, settings)
                app = create_app(Settings(postgres_password="test", live_updates_enabled=False))
                await stack.enter_async_context(app.router.lifespan_context(app))
                app.state.settings = settings

                def dependency(factory):
                    async def session_factory():
                        async with factory() as s:
                            yield s

                    return session_factory

                app.dependency_overrides[get_session] = dependency(sessions)
                api = await stack.enter_async_context(
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app), base_url="http://" + mode
                    )
                )
                await login_test_admin(api, sessions)
                nodes.append(
                    SimpleNamespace(api=api, db=db, settings=settings, app=app, sessions=sessions)
                )
            edge, cloud = nodes
            response = await cloud.api.post(
                "/api/sync/installations",
                json={"id": identity, "name": "Test Edge", "token": TOKEN},
            )
            assert response.status_code == 201, response.text
            http = await stack.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=cloud.app), base_url="http://cloud/"
                )
            )
            client = SyncClient(edge.db, edge.settings, http)
            yield edge, cloud, client, identity
        finally:
            await stack.aclose()
            for engine in engines:
                await engine.dispose()
            for schema in schemas:
                async with admin.begin() as c:
                    await c.execute(DropSchema(schema, cascade=True))
            await admin.dispose()


async def drain(client, edge):
    for _ in range(100):
        await client.cycle()
        async with edge.sessions() as s:
            if not await s.scalar(select(func.count()).select_from(SyncOutbox)):
                return
        await asyncio.sleep(0.1)
    async with edge.sessions() as s:
        pending = list(await s.scalars(select(SyncOutbox)))
        raise AssertionError([(r.entity, r.operation, r.payload) for r in pending])


async def fixture_tag(edge):
    await worker(edge.sessions, mode="simulator")
    return await setup_tag(
        edge.api, register_type="coil", data_type="bool", writable=True, history_enabled=True
    )


async def test_store_forward_duplicates_remote_command_and_alarm(pair):
    edge, cloud, client, identity = pair
    tag = await fixture_tag(edge)
    now = datetime.now(UTC)
    async with edge.sessions() as s, s.begin():
        await upsert_current(s, tag["id"], reading=Reading(False, now, source="simulator"))
    async with edge.sessions() as s:
        captured = list(await s.scalars(select(SyncOutbox).order_by(SyncOutbox.id)))
        assert any(r.entity == "tag_history" for r in captured)
        batch = {
            "version": 1,
            "events": [
                {
                    "event_id": r.event_id,
                    "sequence": r.id,
                    "entity": r.entity,
                    "operation": r.operation,
                    "payload": r.payload,
                }
                for r in captured
            ],
        }
    await drain(client, edge)
    tags = (await cloud.api.get("/api/tags")).json()
    assert len(tags) == 1
    cloud_tag = tags[0]
    assert cloud_tag["name"] == tag["name"]
    current = (await cloud.api.get(f"/api/tags/{cloud_tag['id']}/value")).json()
    assert current["value_boolean"] is False and current["source"] == "simulator"
    headers = {"Authorization": "Bearer " + TOKEN, "X-Edge-ID": identity}
    for _ in range(2):
        response = await cloud.api.post("/api/sync/v1/events", json=batch, headers=headers)
        assert response.status_code == 200, response.text
    async with cloud.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(TagHistory)) == 1
    request_id = str(uuid4())
    response = await cloud.api.post(
        f"/api/tags/{cloud_tag['id']}/commands", json={"value": True, "request_id": request_id}
    )
    assert response.status_code == 202, response.text
    remote = response.json()
    assert remote["status"] == "PENDING_EDGE"
    await client.cycle()
    await client.cycle()
    async with edge.sessions() as s:
        commands = list(await s.scalars(select(Command)))
        assert len(commands) == 1 and commands[0].request_id == request_id
        assert commands[0].requested_by is None and commands[0].requested_by_username.startswith(
            "Cloud:"
        )
        command_id = commands[0].id
    processor = CommandProcessor(edge.db, edge.settings, SimulatorSource())
    await processor.claim()
    await processor.process(command_id)
    await drain(client, edge)
    result = (await cloud.api.get(f"/api/commands/{remote['id']}")).json()
    assert result["status"] == "SUCCESS" and result["verified_value"] is True
    assert result["requested_by_username"] == "test_admin"
    # Alarm lifecycle and remote acknowledgement use the same local alarm record.
    rule = await edge.api.post(
        "/api/alarms/rules",
        json={
            "name": "Boolean test",
            "tag_id": tag["id"],
            "operator": "==",
            "value": True,
            "enabled": True,
        },
    )
    assert rule.status_code == 201, rule.text
    from app.worker.alarms import AlarmEngine

    await AlarmEngine(edge.db, edge.settings).tick()
    await drain(client, edge)
    alarms = (await cloud.api.get("/api/alarms/events")).json()
    assert len(alarms) == 1
    ack = await cloud.api.post(f"/api/alarms/events/{alarms[0]['id']}/acknowledge")
    assert ack.status_code == 200 and ack.json()["state"] == "ACTIVE"
    await drain(client, edge)
    alarms = (await cloud.api.get("/api/alarms/events")).json()
    assert alarms[0]["state"] == "ACKNOWLEDGED" and alarms[0][
        "acknowledged_by_username"
    ].startswith("Cloud:")


async def test_offline_backoff_and_configuration_safety(pair):
    edge, cloud, client, identity = pair
    tag = await fixture_tag(edge)
    real_http = client.http

    async def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    client.http = httpx.AsyncClient(
        base_url="http://cloud/", transport=httpx.MockTransport(unavailable)
    )
    for value in (True, False, True):
        async with edge.sessions() as s, s.begin():
            await upsert_current(
                s, tag["id"], reading=Reading(value, datetime.now(UTC), source="simulator")
            )
    assert await client.step() == 4
    assert await client.step() == 8
    async with edge.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(TagHistory)) == 3
        assert await s.scalar(select(func.count()).select_from(SyncOutbox)) > 0
    await client.http.aclose()
    client.http = real_http
    await drain(client, edge)
    async with cloud.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(TagHistory)) == 3
    ctag = (await cloud.api.get("/api/tags")).json()[0]
    assert (
        await cloud.api.patch(f"/api/tags/{ctag['id']}", json={"enabled": False})
    ).status_code == 409
    response = await cloud.api.post(f"/api/tags/{ctag['id']}/commands", json={"value": False})
    assert response.status_code == 202, response.text
    await edge.api.patch(f"/api/tags/{tag['id']}", json={"description": "Changed after enqueue"})
    await drain(client, edge)
    result = (await cloud.api.get(f"/api/commands/{response.json()['id']}")).json()
    assert result["status"] == "FAILED" and "configuration changed" in result["error_message"]
    async with edge.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(Command)) == 0


async def test_machine_auth_expiry_and_multiple_installations(pair):
    edge, cloud, client, identity = pair
    assert (await cloud.api.post("/api/sync/v1/heartbeat", json={})).status_code == 401
    assert (await edge.api.post("/api/sync/v1/heartbeat", json={})).status_code == 404
    await fixture_tag(edge)
    await drain(client, edge)
    ctag = (await cloud.api.get("/api/tags")).json()[0]
    command_response = await cloud.api.post(
        f"/api/tags/{ctag['id']}/commands", json={"value": True}
    )
    assert command_response.status_code == 202, command_response.text
    async with cloud.sessions() as s, s.begin():
        await s.execute(
            update(RemoteRequest).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await client.cycle()
    assert (await cloud.api.get(f"/api/commands/{command_response.json()['id']}")).json()[
        "status"
    ] == "EXPIRED"
    async with edge.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(Command)) == 0
    # Equal local IDs from another installation must allocate distinct relational Cloud IDs.
    second = str(uuid4())
    await cloud.api.post(
        "/api/sync/installations", json={"id": second, "name": "Second Edge", "token": TOKEN}
    )
    async with cloud.sessions() as s:
        from app.models import SyncMapping

        rows = list(
            await s.scalars(
                select(SyncMapping)
                .where(SyncMapping.edge_id == identity)
                .order_by(SyncMapping.sequence)
            )
        )
    events = [
        {
            "event_id": str(uuid4()),
            "sequence": n + 1,
            "entity": r.entity,
            "operation": "upsert",
            "payload": r.original,
        }
        for n, r in enumerate(rows)
        if r.entity in ("connections", "devices", "tags")
    ]
    response = await cloud.api.post(
        "/api/sync/v1/events",
        json={"events": events},
        headers={"Authorization": "Bearer " + TOKEN, "X-Edge-ID": second},
    )
    assert response.status_code == 200, response.text
    tags = (await cloud.api.get("/api/tags")).json()
    assert len(tags) == 2 and tags[0]["id"] != tags[1]["id"] and tags[0]["key"] != tags[1]["key"]
    assert "token" not in (await cloud.api.get("/api/sync/status")).text


async def test_edge_expired_duplicate_delivery(pair):
    edge, cloud, client, identity = pair
    action = RemoteAction(
        id=uuid4(),
        edge_id=identity,
        kind="command",
        target_id=1,
        user_id=123,
        username="cloud_operator",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        payload={},
    )
    for _ in range(2):
        async with edge.sessions() as s, s.begin():
            result = await accept_remote(s, edge.settings, action, identity)
            assert result.status == "EXPIRED"
    async with edge.sessions() as s:
        assert await s.scalar(select(func.count()).select_from(RemoteInbox)) == 1
        assert await s.scalar(select(func.count()).select_from(Command)) == 0


async def test_cloud_cannot_create_transport_and_https_required():
    from app.worker.modbus import ConnectionManager

    with pytest.raises(RuntimeError, match="Cloud"):
        ConnectionManager(Settings(postgres_password="test", application_mode="cloud"))
    with pytest.raises(ValueError, match="HTTPS"):
        SyncClient(
            None,
            Settings(postgres_password="test", sync_cloud_url="http://cloud", sync_token=TOKEN),
        )
    with pytest.raises(ValueError):
        Batch.model_validate(
            {
                "events": [
                    {
                        "entity": "users",
                        "event_id": str(uuid4()),
                        "sequence": 1,
                        "operation": "upsert",
                        "payload": {},
                    }
                ]
            }
        )


async def test_layout_recreation_and_transactional_capture(pair):
    from sqlalchemy import delete, insert

    from app.models import DashboardWidgetLayout
    from tests.test_dashboards import dashboard, widget

    edge, cloud, client, identity = pair
    tag = await fixture_tag(edge)
    board = await dashboard(edge.api)
    response = await edge.api.post(
        f"/api/dashboards/{board['id']}/widgets", json=widget([tag["id"]])
    )
    assert response.status_code == 201
    widget_id = response.json()["id"]
    await drain(client, edge)
    async with edge.sessions() as s:
        await s.execute(
            delete(DashboardWidgetLayout).where(DashboardWidgetLayout.widget_id == widget_id)
        )
        await s.rollback()
        assert await s.scalar(select(func.count()).select_from(SyncOutbox)) == 0
    async with edge.sessions() as s, s.begin():
        layouts = (
            (
                await s.execute(
                    select(DashboardWidgetLayout.__table__).where(
                        DashboardWidgetLayout.widget_id == widget_id
                    )
                )
            )
            .mappings()
            .all()
        )
        await s.execute(
            delete(DashboardWidgetLayout).where(DashboardWidgetLayout.widget_id == widget_id)
        )
        for layout in layouts:
            await s.execute(insert(DashboardWidgetLayout).values(**(dict(layout) | {"y": 9})))
    await drain(client, edge)
    async with cloud.sessions() as s:
        layouts = list(await s.scalars(select(DashboardWidgetLayout)))
        assert len(layouts) == 3
        assert all(row.y == 9 for row in layouts)


async def test_invalid_row_does_not_block_valid_batch_event(pair):
    edge, cloud, client, identity = pair
    await fixture_tag(edge)
    async with edge.sessions() as s:
        row = await s.scalar(select(SyncOutbox).where(SyncOutbox.entity == "connections"))
        good = {
            "event_id": row.event_id,
            "sequence": row.id,
            "entity": row.entity,
            "operation": row.operation,
            "payload": row.payload,
        }
    bad = good | {"event_id": str(uuid4()), "payload": {"secret": "must-not-echo"}}
    response = await cloud.api.post(
        "/api/sync/v1/events",
        json={"events": [bad, good]},
        headers={"Authorization": "Bearer " + TOKEN, "X-Edge-ID": identity},
    )
    assert response.status_code == 200
    assert response.json()["acknowledged"] == [good["event_id"]]
    assert response.json()["deferred"][0]["event_id"] == bad["event_id"]
    assert "must-not-echo" not in response.text


async def test_deferred_child_does_not_starve_parent_metadata(pair):
    from sqlalchemy import delete

    edge, cloud, client, identity = pair
    parent = (await edge.api.post("/api/locations", json={"name": "Parent"})).json()
    response = await edge.api.post(
        "/api/locations", json={"name": "Child", "parent_id": parent["id"]}
    )
    assert response.status_code == 201
    async with edge.sessions() as s, s.begin():
        rows = list(
            await s.scalars(
                select(SyncOutbox)
                .where(SyncOutbox.entity == "locations")
                .order_by(SyncOutbox.id.desc())
            )
        )
        payloads = [row.payload for row in rows]
        await s.execute(delete(SyncOutbox))
        for payload in payloads:
            s.add(SyncOutbox(entity="locations", operation="upsert", priority=0, payload=payload))
            await s.flush()
    client.settings.sync_batch_size = 6
    await client.cycle()  # Child cannot resolve its parent yet.
    await client.cycle()  # Must advance to parent instead of immediately retrying child.
    assert len((await cloud.api.get("/api/locations")).json()) == 1
    async with edge.sessions() as s, s.begin():
        await s.execute(
            update(SyncOutbox).values(retry_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await client.cycle()
    assert len((await cloud.api.get("/api/locations")).json()) == 2


async def test_sync_migration_downgrade_upgrade_matches_models(pair):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.base import Base

    edge, cloud, client, identity = pair
    engine = cloud.sessions.kw["bind"]

    def check(connection):
        config = Config("server/alembic.ini")
        config.attributes["connection"] = connection
        command.downgrade(config, "0011_auth")
        command.upgrade(config, "head")
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert differences == []

    async with engine.begin() as connection:
        await connection.run_sync(check)
