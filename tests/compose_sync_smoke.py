"""Disposable Edge+Cloud, independent PostgreSQL volumes, simulation only, no Telegram."""

import asyncio
import json
import os
import secrets
import subprocess
from uuid import uuid4

import httpx
from compose_auth_helpers import bootstrap_login, browser_session, ws_headers
from compose_modbus_smoke import free_port
from compose_sync_backlog import verify_backlog
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect


async def main():
    project = "modbus-sync-test-" + uuid4().hex[:10]
    edge_port, cloud_port, ui_port = free_port(), free_port(), free_port()
    identity = str(uuid4())
    token = secrets.token_urlsafe(40)
    env = {
        **os.environ,
        "SYNC_TEST_DB_PASSWORD": secrets.token_urlsafe(24),
        "SYNC_TEST_EDGE_ID": identity,
        "SYNC_TEST_TOKEN": token,
        "SYNC_TEST_EDGE_PORT": str(edge_port),
        "SYNC_TEST_CLOUD_PORT": str(cloud_port),
        "SYNC_TEST_UI_PORT": str(ui_port),
        "SYNC_TEST_CORS": json.dumps([f"http://localhost:{ui_port}"]),
    }
    prefix = ["docker", "compose", "-p", project, "-f", "tests/docker-compose.sync-test.yml"]

    async def compose(*args):
        result = await asyncio.to_thread(
            subprocess.run, [*prefix, *args], env=env, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout

    async def until(check, timeout=60):
        async with asyncio.timeout(timeout):
            while True:
                result = await check()
                if result:
                    return result
                await asyncio.sleep(0.25)

    async def create(api, path, **payload):
        response = await api.post("/api/" + path, json=payload)
        response.raise_for_status()
        return response.json()

    async def rows(api, path):
        response = await api.get("/api/" + path)
        response.raise_for_status()
        return response.json()

    async def completed(api, identifier):
        row = await rows(api, f"commands/{identifier}")
        assert row["status"] not in ("FAILED", "EXPIRED", "CANCELLED"), row
        return row if row["status"] == "SUCCESS" else None

    async def local_write(api, tag, value):
        command = await create(api, f"tags/{tag['id']}/commands", value=value)
        return await until(lambda: completed(api, command["id"]))

    try:
        await compose("config", "--quiet")
        await compose("up", "-d", "--no-build", "--wait")
        async with (
            httpx.AsyncClient(base_url=f"http://localhost:{edge_port}", timeout=15) as edge,
            httpx.AsyncClient(base_url=f"http://localhost:{cloud_port}", timeout=15) as cloud,
        ):
            await bootstrap_login(prefix, env, edge, "edge-api")
            await bootstrap_login(prefix, env, cloud, "cloud-api")
            await create(
                cloud, "sync/installations", id=identity, name="Remote test Edge", token=token
            )
            connection = await create(
                edge,
                "connections",
                name="Simulator transport",
                protocol="modbus_tcp",
                host="unused.invalid",
            )
            device = await create(
                edge,
                "devices",
                name="Simulated equipment",
                connection_id=connection["id"],
                slave_id=1,
            )

            async def tag(key, dtype, address):
                return await create(
                    edge,
                    "tags",
                    name=key,
                    key=key,
                    device_id=device["id"],
                    register_type="coil" if dtype == "bool" else "holding_register",
                    address=address,
                    data_type=dtype,
                    writable=True,
                    poll_interval_ms=1000,
                    history_enabled=True,
                )

            numeric = await tag("remote_numeric", "float32", 0)
            relay = await tag("remote_relay", "bool", 0)
            trigger = await tag("local_trigger", "bool", 1)
            await local_write(edge, relay, False)
            await local_write(edge, trigger, False)
            board = await create(
                edge, "dashboards", name="Remote board", slug="remote-board", is_default=True
            )
            for index, (kind, title, ids) in enumerate(
                [
                    ("value", "Remote value", [numeric["id"]]),
                    ("chart", "Remote history", [numeric["id"]]),
                    ("switch", "Remote control", [relay["id"]]),
                    ("alarms", "Remote alarms", []),
                ]
            ):
                await create(
                    edge,
                    f"dashboards/{board['id']}/widgets",
                    type=kind,
                    title=title,
                    tag_ids=ids,
                    configuration={},
                    layouts=[
                        {"breakpoint": b, "x": 0, "y": index * 12, "w": w, "h": 12}
                        for b, w in [("lg", 6), ("md", 6), ("sm", 1)]
                    ],
                )
            await create(
                edge,
                "alarms/rules",
                name="Remote boolean alarm",
                tag_id=relay["id"],
                operator="==",
                value=True,
                enabled=True,
                notification_enabled=False,
            )
            await create(
                edge,
                "automation/rules",
                name="Local offline rule",
                enabled=True,
                conditions=[{"tag_id": trigger["id"], "operator": "==", "value": True}],
                actions=[{"target_tag_id": relay["id"], "value": True}],
            )

            async def mirror_ready():
                tags = await rows(cloud, "tags")
                boards = await rows(cloud, "dashboards")
                return tags if len(tags) == 3 and boards else None

            tags = await until(mirror_ready)
            cnum = next(t for t in tags if t["name"] == numeric["name"])
            crelay = next(t for t in tags if t["name"] == relay["name"])

            async def history_ready():
                h = await rows(cloud, f"tags/{cnum['id']}/history")
                return h if h["total_count"] >= 3 else None

            await until(history_ready)
            async with connect(
                f"ws://localhost:{cloud_port}/api/ws/live",
                additional_headers=ws_headers(cloud),
                origin=f"http://localhost:{ui_port}",
            ) as socket:
                assert json.loads(await socket.recv())["type"] == "ready"

                async def telemetry():
                    while True:
                        value = json.loads(await socket.recv())
                        if value["type"] == "tag_value":
                            return value

                await asyncio.wait_for(telemetry(), 15)
            print(
                "PASS: Edge -> Cloud metadata, typed current/history, dashboards, authenticated WebSocket"
            )
            previous = (await rows(edge, f"tags/{numeric['id']}/history"))["total_count"]
            await compose("stop", "cloud-api")
            await local_write(edge, trigger, True)

            async def automated():
                commands = await rows(edge, "commands")
                return next(
                    (
                        c
                        for c in commands
                        if c["source"] == "automation" and c["status"] == "SUCCESS"
                    ),
                    None,
                )

            await until(automated)

            async def collecting_offline():
                h = await rows(edge, f"tags/{numeric['id']}/history")
                s = await rows(edge, "sync/status")
                return h["total_count"] >= previous + 3 and s["pending"] > 0

            await until(collecting_offline)
            print(
                "PASS: Cloud disconnected; local telemetry, history, Automation and verified control continue"
            )
            await compose("start", "cloud-api")

            async def healthy():
                try:
                    return (await cloud.get("/api/health/db")).status_code == 200
                except httpx.HTTPError:
                    return False

            await until(healthy)

            async def caught_up():
                h = await rows(cloud, f"tags/{cnum['id']}/history")
                return h["total_count"] >= previous + 3

            await until(caught_up)

            async def alarm_ready():
                alarms = await rows(cloud, "alarms/events?active=true")
                return alarms[0] if alarms else None

            event = await until(alarm_ready)
            response = await cloud.post(f"/api/alarms/events/{event['id']}/acknowledge")
            response.raise_for_status()

            async def acknowledged():
                return any(e["state"] == "ACKNOWLEDGED" for e in await rows(edge, "alarms/events"))

            await until(acknowledged)
            remote = await create(cloud, f"tags/{crelay['id']}/commands", value=False)
            assert remote["status"] == "PENDING_EDGE"
            # Repeated HTTP enqueue has stable request_id and does not create another remote/local command.
            duplicate = await create(
                cloud, f"tags/{crelay['id']}/commands", value=False, request_id=remote["request_id"]
            )
            assert duplicate["id"] == remote["id"]
            result = await until(lambda: completed(cloud, remote["id"]))
            assert result["verified_value"] is False
            local = await rows(edge, "commands?request_id=" + remote["request_id"])
            assert (
                len(local) == 1
                and local[0]["status"] == "SUCCESS"
                and local[0]["requested_by"] is None
            )
            print(
                "PASS: backlog catches up, remote alarm acknowledgement, exactly one local simulated command + verified result"
            )
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="msedge", headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 390, "height": 844})
                    await browser_session(page, cloud)
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    await page.goto(f"http://localhost:{ui_port}/dashboard")
                    await page.get_by_role("heading", name="Remote value", exact=True).wait_for()
                    await page.get_by_role("img", name="Historical line chart").wait_for()
                    assert (
                        await page.get_by_role("button", name="Edit layout", exact=True).count()
                        == 0
                    )
                    await page.get_by_role("button", name="Apply", exact=True).wait_for(
                        state="visible"
                    )
                    await page.goto(f"http://localhost:{ui_port}/settings")
                    await page.get_by_text("Remote test Edge: ONLINE", exact=True).wait_for()
                    assert await page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), "Mobile overflow"
                    assert not errors, errors
                finally:
                    await browser.close()
            print(
                "PASS: mobile Cloud dashboard/chart/control, read-only configuration, Edge status UI"
            )
            await verify_backlog(edge, cloud, device, compose, create, rows, until)
            for service in ("edge-api", "cloud-api"):
                await compose("exec", "-T", service, "alembic", "check")
            logs = await compose(
                "logs", "--no-color", "edge-api", "cloud-api", "edge-worker", "edge-sync"
            )
            assert token not in logs and env["SYNC_TEST_DB_PASSWORD"] not in logs
            assert "Traceback" not in logs and "Unhandled request error" not in logs, logs[-3000:]
            print(
                "PASS: separate PostgreSQL databases, Alembic metadata, secret-free logs, no physical writes"
            )
    finally:
        await compose("down", "-v", "--remove-orphans")
        print("Removed isolated Edge/Cloud fixtures and both database volumes")


if __name__ == "__main__":
    asyncio.run(main())
