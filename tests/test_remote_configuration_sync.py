"""Full API -> Cloud queue -> Edge CRUD -> metadata/result mirror on PostgreSQL."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select

import tests.test_sync as sync_tests
from app.models import Location, RemoteInbox, RemoteRequest, User
from tests.test_sync import drain

pair = sync_tests.pair

pytestmark = pytest.mark.anyio


async def submit(cloud, method, path, payload, *, edge_id=None):
    data = {
        "request_id": str(uuid4()),
        "method": method,
        "path": path,
        "payload": payload,
    }
    if edge_id:
        data["edge_id"] = edge_id
    if path.rsplit("/", 1)[-1].isdigit() or path.endswith(("/widgets", "/layout")):
        target = (
            path.rsplit("/", 1)[0] if path.endswith(("/widgets", "/layout")) else path
        )
        context = await cloud.api.get(
            "/api/sync/configuration/context", params={"path": target}
        )
        assert context.status_code == 200, context.text
        data["expected_updated_at"] = context.json()["updated_at"]
    response = await cloud.api.post("/api/sync/configuration/requests", json=data)
    assert response.status_code == 202, response.text
    return data, response.json()


async def finished(cloud, client, edge, identifier):
    await drain(client, edge)
    response = await cloud.api.get("/api/sync/configuration/requests/" + identifier)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["status"] == "SUCCESS", row
    return row["data"]


async def test_remote_crud_idempotency_and_ordinary_cloud_guard(pair):
    edge, cloud, client, identity = pair
    await client.cycle()
    me = (await cloud.api.get("/api/auth/me")).json()
    assert (
        "remote_configure" in me["permissions"] and "configure" not in me["permissions"]
    )
    assert (
        await cloud.api.post("/api/locations", json={"name": "Forbidden direct"})
    ).status_code == 409
    payload, queued = await submit(
        cloud, "POST", "locations", {"name": "Remote room"}, edge_id=identity
    )
    again = await cloud.api.post("/api/sync/configuration/requests", json=payload)
    assert again.status_code == 202 and again.json()["id"] == queued["id"]
    row = await finished(cloud, client, edge, queued["id"])
    assert row["name"] == "Remote room"
    _, change = await submit(
        cloud, "PATCH", f"locations/{row['id']}", {"name": "Edited remotely"}
    )
    row = await finished(cloud, client, edge, change["id"])
    assert row["name"] == "Edited remotely"
    async with edge.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Location)) == 1
        assert await session.scalar(select(func.count()).select_from(RemoteInbox)) == 2
    _, deletion = await submit(cloud, "DELETE", f"locations/{row['id']}", {})
    await finished(cloud, client, edge, deletion["id"])
    assert (await cloud.api.get("/api/locations")).json() == []


async def test_remote_dashboard_widget_and_default_context(pair):
    edge, cloud, client, identity = pair
    await client.cycle()
    _, queued = await submit(
        cloud,
        "POST",
        "dashboards",
        {"name": "Operations", "slug": "ops", "is_default": True},
        edge_id=identity,
    )
    dashboard = await finished(cloud, client, edge, queued["id"])
    ctx = (
        await cloud.api.get(
            "/api/sync/configuration/context",
            params={"path": f"dashboards/{dashboard['id']}"},
        )
    ).json()
    assert ctx["record"]["name"] == "Operations" and ctx["record"]["is_default"] is True
    _, queued = await submit(
        cloud, "PATCH", f"dashboards/{dashboard['id']}", {"is_default": False}
    )
    await finished(cloud, client, edge, queued["id"])
    assert (await edge.api.get("/api/dashboards")).json()[0]["is_default"] is False
    _, queued = await submit(
        cloud,
        "POST",
        f"dashboards/{dashboard['id']}/widgets",
        {
            "type": "text",
            "title": "Note",
            "configuration": {"text": "Remote test"},
            "tag_ids": [],
            "layouts": [
                {"breakpoint": "lg", "x": 0, "y": 0, "w": 4, "h": 3},
                {"breakpoint": "md", "x": 0, "y": 0, "w": 4, "h": 3},
                {"breakpoint": "sm", "x": 0, "y": 0, "w": 1, "h": 3},
            ],
        },
    )
    widget = await finished(cloud, client, edge, queued["id"])
    assert widget["title"] == "Note"
    _, queued = await submit(
        cloud, "PATCH", f"dashboard-widgets/{widget['id']}", {"title": "Updated note"}
    )
    widget = await finished(cloud, client, edge, queued["id"])
    assert widget["title"] == "Updated note"
    current = (await cloud.api.get(f"/api/dashboards/{dashboard['id']}")).json()
    layouts = [{"widget_id": widget["id"], **layout} for layout in widget["layouts"]]
    layouts[0]["y"] = 1
    _, queued = await submit(
        cloud,
        "PATCH",
        f"dashboards/{dashboard['id']}/layout",
        {"revision": current["revision"], "layouts": layouts},
    )
    updated = await finished(cloud, client, edge, queued["id"])
    assert updated["revision"] > current["revision"]
    _, queued = await submit(cloud, "DELETE", f"dashboard-widgets/{widget['id']}", {})
    await finished(cloud, client, edge, queued["id"])
    edge_dashboard = (await edge.api.get("/api/dashboards")).json()[0]["id"]
    assert (await edge.api.get(f"/api/dashboards/{edge_dashboard}")).json()[
        "widgets"
    ] == []


async def test_remote_equipment_rules_bindings_and_expiry(pair):
    edge, cloud, client, identity = pair
    await client.cycle()

    async def create(path, payload):
        _, request = await submit(cloud, "POST", path, payload, edge_id=identity)
        return await finished(cloud, client, edge, request["id"])

    connection = await create(
        "connections",
        {"name": "Test transport", "protocol": "modbus_tcp", "host": "unused.test"},
    )
    device = await create(
        "devices",
        {"name": "Test device", "connection_id": connection["id"], "slave_id": 1},
    )
    tag = await create(
        "tags",
        {
            "name": "Test output",
            "key": "test_output",
            "device_id": device["id"],
            "register_type": "coil",
            "address": 0,
            "data_type": "bool",
            "writable": True,
        },
    )
    _, request = await submit(
        cloud, "PATCH", f"tags/{tag['id']}", {"name": "Changed output"}
    )
    assert (await finished(cloud, client, edge, request["id"]))[
        "name"
    ] == "Changed output"
    context = (
        await cloud.api.get(
            "/api/sync/configuration/context", params={"path": f"tags/{tag['id']}"}
        )
    ).json()
    assert context["record"]["key"] == "test_output"
    rule = await create(
        "automation/rules",
        {
            "name": "Disabled test",
            "enabled": False,
            "conditions": [{"tag_id": tag["id"], "operator": "==", "value": False}],
            "actions": [{"target_tag_id": tag["id"], "value": True}],
        },
    )
    assert rule["conditions"][0]["tag_id"] == tag["id"]
    assert rule["actions"][0]["target_tag_id"] == tag["id"]
    _, request = await submit(
        cloud, "PATCH", f"automation/rules/{rule['id']}", {"name": "Changed rule"}
    )
    assert (await finished(cloud, client, edge, request["id"]))[
        "name"
    ] == "Changed rule"
    alarm = await create(
        "alarms/rules",
        {
            "name": "Disabled alarm",
            "enabled": False,
            "notification_enabled": False,
            "tag_id": tag["id"],
            "operator": "==",
            "value": True,
        },
    )
    _, request = await submit(
        cloud, "PATCH", f"alarms/rules/{alarm['id']}", {"severity": "CRITICAL"}
    )
    assert (await finished(cloud, client, edge, request["id"]))[
        "severity"
    ] == "CRITICAL"
    assert (await edge.api.get("/api/commands")).json() == []
    # Expiration must prevent application even if transport returns after a long outage.
    from datetime import UTC, datetime, timedelta

    _, request = await submit(
        cloud, "POST", "locations", {"name": "Must expire"}, edge_id=identity
    )
    async with cloud.sessions() as session, session.begin():
        row = await session.get(RemoteRequest, request["id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await drain(client, edge)
    assert (
        await cloud.api.get("/api/sync/configuration/requests/" + request["id"])
    ).json()["status"] == "EXPIRED"
    assert (await edge.api.get("/api/locations")).json() == []


async def test_remote_authorization_csrf_revocation_and_stale_version(pair):
    edge, cloud, client, identity = pair
    await client.cycle()
    _, queued = await submit(
        cloud, "POST", "locations", {"name": "Room"}, edge_id=identity
    )
    row = await finished(cloud, client, edge, queued["id"])
    data, request = await submit(
        cloud, "PATCH", f"locations/{row['id']}", {"name": "Queued"}
    )
    local_id = (await edge.api.get("/api/locations")).json()[0]["id"]
    await edge.api.patch(f"/api/locations/{local_id}", json={"name": "Local edit"})
    await drain(client, edge)
    assert (
        await cloud.api.get("/api/sync/configuration/requests/" + request["id"])
    ).json()["status"] == "FAILED"
    data["request_id"] = str(uuid4())
    assert (
        await cloud.api.post("/api/sync/configuration/requests", json=data)
    ).status_code == 409
    assert (
        await cloud.api.post(
            "/api/sync/configuration/requests",
            json=data,
            headers={"X-CSRF-Token": "bad"},
        )
    ).status_code == 403
    _, request = await submit(
        cloud, "POST", "locations", {"name": "Cancelled"}, edge_id=identity
    )
    me = (await cloud.api.get("/api/auth/me")).json()
    async with cloud.sessions() as session, session.begin():
        user = await session.get(User, me["id"])
        user.role = "VIEWER"
    assert (await cloud.api.get("/api/sync/configuration/requests")).status_code == 403
    assert (
        await cloud.api.post("/api/sync/configuration/requests", json=data)
    ).status_code == 403
    await drain(client, edge)
    async with cloud.sessions() as session:
        assert (await session.get(RemoteRequest, request["id"])).status == "CANCELLED"
    assert len((await edge.api.get("/api/locations")).json()) == 1


async def test_concurrent_duplicate_enqueue_and_delivery(pair):
    import asyncio

    from app.sync.protocol import RemoteAction
    from app.sync.remote import accept_remote

    edge, cloud, client, identity = pair
    await client.cycle()
    payload = {
        "request_id": str(uuid4()),
        "method": "POST",
        "path": "locations",
        "payload": {"name": "Concurrent"},
        "edge_id": identity,
    }
    responses = await asyncio.gather(
        *[
            cloud.api.post("/api/sync/configuration/requests", json=payload)
            for _ in range(2)
        ]
    )
    assert all(r.status_code == 202 for r in responses)
    headers = {"Authorization": "Bearer " + sync_tests.TOKEN, "X-Edge-ID": identity}
    delivered = (await cloud.api.get("/api/sync/v1/requests", headers=headers)).json()[
        "requests"
    ][0]
    action = RemoteAction.model_validate(delivered)

    async def apply_once():
        async with edge.sessions() as session, session.begin():
            return (
                await accept_remote(session, edge.settings, action, identity)
            ).result

    first, second = await asyncio.gather(apply_once(), apply_once())
    assert first == second
    async with edge.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Location)) == 1
    await finished(cloud, client, edge, payload["request_id"])
