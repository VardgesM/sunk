"""Disposable simulator authentication/authorization integration, no physical writes or Telegram."""

import asyncio
import json
import os
import secrets
import subprocess
from uuid import uuid4

import httpx
from compose_auth_helpers import bootstrap_login, ws_headers
from compose_modbus_smoke import free_port
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus


async def main() -> None:
    project = f"modbus-auth-test-{uuid4().hex[:10]}"
    api_port, ui_port, pg_port = free_port(), free_port(), free_port()
    origin = f"http://localhost:{ui_port}"
    env = {
        **os.environ,
        "APPLICATION_MODE": "standalone",
        "EDGE_INSTALLATION_ID": "",
        "API_PORT": str(api_port),
        "FRONTEND_PORT": str(ui_port),
        "POSTGRES_PORT": str(pg_port),
        "TELEMETRY_SOURCE": "simulator",
        "SIMULATOR_ENABLED": "false",
        "MODBUS_WRITES_ENABLED": "false",
        "TELEGRAM_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "AUTH_COOKIE_SECURE": "false",
        "SIMULATOR_FAILURE_PROBABILITY": "0",
        "WORKER_CONFIG_REFRESH_SECONDS": "0.2",
        "CORS_ORIGINS": json.dumps([origin]),
    }
    prefix = [
        "docker",
        "compose",
        "-p",
        project,
        "-f",
        "docker-compose.yml",
        "-f",
        "tests/docker-compose.modbus-test.yml",
    ]

    async def compose(*args):
        result = await asyncio.to_thread(
            subprocess.run, [*prefix, *args], env=env, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout

    async def until(check):
        async with asyncio.timeout(30):
            while True:
                value = await check()
                if value:
                    return value
                await asyncio.sleep(0.2)

    try:
        await compose("up", "-d", "--no-build", "--wait")
        async with httpx.AsyncClient(base_url=f"http://localhost:{api_port}", timeout=15) as admin:
            assert (await admin.get("/api/tags")).status_code == 401
            username, password = await bootstrap_login(prefix, env, admin)

            async def create(path, **values):
                response = await admin.post("/api/" + path, json=values)
                response.raise_for_status()
                return response.json()

            async def ready():
                return (await admin.get("/api/system/runtime")).json()["mode"] == "simulator"

            await until(ready)
            operator_password, viewer_password = (
                secrets.token_urlsafe(20),
                secrets.token_urlsafe(20),
            )
            operator = await create(
                "users", username="operator", password=operator_password, role="OPERATOR"
            )
            viewer = await create(
                "users", username="viewer", password=viewer_password, role="VIEWER"
            )
            connection = await create(
                "connections",
                name="Authentication simulation",
                protocol="modbus_tcp",
                host="unused.invalid",
            )
            device = await create(
                "devices",
                name="Authentication simulator",
                connection_id=connection["id"],
                slave_id=1,
            )
            tag = await create(
                "tags",
                name="Simulated output",
                key="simulated_output",
                device_id=device["id"],
                register_type="coil",
                address=0,
                data_type="bool",
                writable=True,
                poll_interval_ms=300,
                history_enabled=True,
            )
            board = await create(
                "dashboards",
                name="Authorization dashboard",
                slug="authorization-dashboard",
                is_default=True,
            )
            for index, kind in enumerate(("value", "switch")):
                await create(
                    f"dashboards/{board['id']}/widgets",
                    title=f"Output {kind}",
                    type=kind,
                    tag_ids=[tag["id"]],
                    layouts=[
                        {"breakpoint": b, "x": 0, "y": index * 12, "w": w, "h": 12}
                        for b, w in (("lg", 6), ("md", 6), ("sm", 1))
                    ],
                )
            rule = await create(
                "alarms/rules",
                name="Output active",
                tag_id=tag["id"],
                operator="==",
                value=True,
                severity="INFO",
                enabled=True,
                notification_enabled=False,
            )
            async with (
                httpx.AsyncClient(base_url=str(admin.base_url)) as op,
                httpx.AsyncClient(base_url=str(admin.base_url)) as view,
            ):
                for client, name, secret in (
                    (op, "operator", operator_password),
                    (view, "viewer", viewer_password),
                ):
                    result = await client.post(
                        "/api/auth/login", json={"username": name, "password": secret}
                    )
                    assert result.status_code == 200
                    client.headers["X-CSRF-Token"] = client.cookies["mm_csrf"]
                assert (await view.get("/api/dashboards")).status_code == 200
                assert (await view.get("/api/tags/values")).status_code == 200
                assert (
                    await view.post(f"/api/tags/{tag['id']}/commands", json={"value": True})
                ).status_code == 403
                assert (
                    await op.patch(f"/api/tags/{tag['id']}", json={"enabled": False})
                ).status_code == 403
                assert (
                    await op.patch(f"/api/alarms/rules/{rule['id']}", json={"enabled": False})
                ).status_code == 403
                assert (await op.post("/api/automation/rules", json={})).status_code == 403
                command = (
                    await op.post(f"/api/tags/{tag['id']}/commands", json={"value": True})
                ).json()

                async def complete():
                    row = (await op.get(f"/api/commands/{command['id']}")).json()
                    assert row["status"] not in ("FAILED", "EXPIRED", "CANCELLED"), row
                    return row if row["status"] == "SUCCESS" else None

                verified = await until(complete)
                assert (
                    verified["requested_by"] == operator["id"]
                    and verified["verified_value"] is True
                )

                async def active():
                    rows = (
                        await op.get(f"/api/alarms/events?rule_id={rule['id']}&active=true")
                    ).json()
                    return rows[0] if rows else None

                event = await until(active)
                assert (
                    await view.post(f"/api/alarms/events/{event['id']}/acknowledge")
                ).status_code == 403
                ack = await op.post(f"/api/alarms/events/{event['id']}/acknowledge")
                assert ack.json()["acknowledged_by"] == operator["id"]
                try:
                    async with connect(f"ws://localhost:{api_port}/api/ws/live"):
                        raise AssertionError("Anonymous WebSocket accepted")
                except InvalidStatus as error:
                    assert error.response.status_code == 403
                async with connect(
                    f"ws://localhost:{api_port}/api/ws/live", additional_headers=ws_headers(view)
                ) as ws:
                    assert json.loads(await ws.recv())["type"] == "ready"
                    assert (
                        await admin.patch(f"/api/users/{viewer['id']}", json={"enabled": False})
                    ).status_code == 200
                    try:
                        async with asyncio.timeout(5):
                            while True:
                                await ws.recv()
                    except ConnectionClosed as error:
                        assert error.rcvd.code == 4401
                assert (await view.get("/api/tags")).status_code == 401
                await admin.patch(f"/api/users/{viewer['id']}", json={"enabled": True})
            print(
                "PASS: ADMIN/OPERATOR/VIEWER HTTP permissions, simulator verified command, acknowledgement attribution, anonymous socket denial and session revocation",
                flush=True,
            )
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="msedge", headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 390, "height": 844})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))

                    async def login(name, secret):
                        await page.get_by_label("Username").fill(name)
                        await page.get_by_label("Password").fill(secret)
                        await page.get_by_role("button", name="Sign in", exact=True).click()
                        await page.get_by_role("heading", name="Dashboards", exact=True).wait_for()

                    await page.goto(origin + "/dashboard")
                    await login("viewer", viewer_password)
                    await page.get_by_text("Read-only access", exact=True).wait_for()
                    assert await page.get_by_role("button", name="Apply", exact=True).count() == 0
                    assert (
                        await page.get_by_role(
                            "button", name="Create dashboard", exact=True
                        ).count()
                        == 0
                    )
                    await page.get_by_role("button", name="Logout", exact=True).click()
                    await login("operator", operator_password)
                    await page.get_by_role("button", name="Apply", exact=True).wait_for()
                    assert (
                        await page.get_by_role(
                            "button", name="Edit dashboard layout", exact=True
                        ).count()
                        == 0
                    )
                    await page.get_by_role("button", name="Apply", exact=True).click()
                    await page.get_by_role("button", name="Confirm write", exact=True).click()
                    await page.get_by_text("Verified: OFF", exact=True).wait_for()
                    await page.get_by_role("button", name="Logout", exact=True).click()
                    await login(username, password)
                    await page.get_by_role("button", name="Create dashboard", exact=True).wait_for()
                    await page.goto(origin + "/users")
                    await page.get_by_role("heading", name="Users", exact=True).wait_for()
                    await page.get_by_role("button", name="Create user", exact=True).wait_for()
                    await page.goto(origin + "/audit")
                    await page.get_by_role("heading", name="Audit", exact=True).wait_for()
                    await page.get_by_text("commands.request", exact=False).first.wait_for()
                    assert await page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    assert not errors, errors
                    print(
                        "PASS: browser login/logout, mobile roles, VIEWER read-only dashboard, OPERATOR control, ADMIN Users/Audit",
                        flush=True,
                    )
                finally:
                    await browser.close()
            rows = (await admin.get("/api/audit?action=commands.request")).json()
            assert rows and all(row["user_id"] == operator["id"] for row in rows)
            assert not any(
                secret in json.dumps(rows)
                for secret in (password, operator_password, viewer_password)
            )
            await compose("exec", "-T", "api", "alembic", "check")
            logs = await compose("logs", "--no-color", "api", "worker")
            assert not any(
                secret in logs for secret in (password, operator_password, viewer_password)
            )
            assert '"level": "ERROR"' not in logs, logs[-6000:]
            print("PASS: audit history, secret-free logs, Alembic metadata", flush=True)
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Removed isolated authentication fixtures and database", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
