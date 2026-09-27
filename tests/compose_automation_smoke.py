"""Phase 7 integration in a disposable simulator-only Compose project. No physical I/O."""

import asyncio
import json
import os
import subprocess
from uuid import uuid4

import httpx
from compose_auth_helpers import bootstrap_login, browser_session, ws_headers
from compose_modbus_smoke import free_port
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect


async def main() -> None:
    project = f"modbus-automation-test-{uuid4().hex[:10]}"
    api_port, ui_port, pg_port = free_port(), free_port(), free_port()
    env = {
        **os.environ,
        "APPLICATION_MODE": "standalone",
        "EDGE_INSTALLATION_ID": "",
        "TELEGRAM_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "AUTH_COOKIE_SECURE": "false",
        "API_PORT": str(api_port),
        "FRONTEND_PORT": str(ui_port),
        "POSTGRES_PORT": str(pg_port),
        "TELEMETRY_SOURCE": "simulator",
        "SIMULATOR_ENABLED": "false",
        "MODBUS_WRITES_ENABLED": "false",
        "SIMULATOR_FAILURE_PROBABILITY": "0",
        "WORKER_CONFIG_REFRESH_SECONDS": "0.2",
        "CORS_ORIGINS": json.dumps([f"http://localhost:{ui_port}"]),
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

    try:
        await compose("up", "-d", "--no-build", "--wait")
        async with httpx.AsyncClient(
            base_url=f"http://localhost:{api_port}/api", timeout=15
        ) as api:
            await bootstrap_login(prefix, env, api)

            async def create(path, **values):
                r = await api.post(path, json=values)
                r.raise_for_status()
                return r.json()

            async def until(check, timeout=20):
                async with asyncio.timeout(timeout):
                    while True:
                        value = await check()
                        if value:
                            return value
                        await asyncio.sleep(0.1)

            async def ready():
                return (await api.get("/system/runtime")).json()["mode"] == "simulator"

            await until(ready)
            c = await create(
                "/connections",
                name="Isolated simulation",
                protocol="modbus_tcp",
                host="unused.invalid",
            )
            d = await create("/devices", name="Test only", connection_id=c["id"], slave_id=1)

            async def tag(key, dtype, address):
                return await create(
                    "/tags",
                    name=key,
                    key=key,
                    device_id=d["id"],
                    register_type="coil" if dtype == "bool" else "holding_register",
                    data_type=dtype,
                    address=address,
                    writable=True,
                    poll_interval_ms=200,
                    history_enabled=True,
                )

            input_a = await tag("input_a", "float32", 0)
            input_b = await tag("input_b", "float32", 2)
            relay = await tag("relay", "bool", 0)

            async def completed(identifier):
                row = (await api.get(f"/commands/{identifier}")).json()
                if row["status"] in ("FAILED", "EXPIRED", "CANCELLED"):
                    raise AssertionError(row)
                return row if row["status"] == "SUCCESS" else None

            async def set_value(t, value):
                cmd = await create(f"/tags/{t['id']}/commands", value=value)
                return await until(lambda: completed(cmd["id"]))

            await set_value(input_a, "20")
            await set_value(input_b, "20")
            await set_value(relay, False)
            on = await create(
                "/automation/rules",
                name="Above threshold",
                enabled=True,
                for_duration_ms=2000,
                cooldown_ms=1000,
                priority=50,
                condition_mode="ALL",
                conditions=[
                    {"tag_id": input_a["id"], "operator": ">", "value": "30", "hysteresis": "2"}
                ],
                actions=[{"target_tag_id": relay["id"], "value": True}],
            )
            off = await create(
                "/automation/rules",
                name="Below reset",
                enabled=True,
                priority=40,
                conditions=[{"tag_id": input_a["id"], "operator": "<=", "value": "28"}],
                actions=[{"target_tag_id": relay["id"], "value": False}],
            )

            async def executions(rule):
                return (await api.get(f"/automation/rules/{rule['id']}/executions")).json()

            async def success(rule, count=1):
                rows = await executions(rule)
                return rows if sum(r["result"] == "SUCCESS" for r in rows) >= count else None

            await until(lambda: success(off))
            await asyncio.sleep(0.3)
            async with connect(
                f"ws://localhost:{api_port}/api/ws/live", additional_headers=ws_headers(api)
            ) as ws:
                events = []

                async def receive():
                    async for raw in ws:
                        events.append(json.loads(raw))

                listener = asyncio.create_task(receive())
                try:
                    await set_value(input_a, "31")
                    await asyncio.sleep(0.5)
                    assert not await executions(on), "FOR must prevent immediate command creation"
                    await until(lambda: success(on))
                    rows = await executions(on)
                    cmd = (await api.get(f"/commands/{rows[0]['command_ids'][0]}")).json()
                    assert cmd["source"] == "automation" and cmd["verified_value"] is True
                    await asyncio.sleep(2.5)
                    assert len(await executions(on)) == 1, "Continuous true must not repeat"
                    for value in ("29.9", "30.1", "29.95", "30.2"):
                        await set_value(input_a, value)
                        await asyncio.sleep(0.3)
                    assert len(await executions(on)) == 1
                    await set_value(input_a, "27")
                    await until(lambda: success(off, 2))
                    assert (await api.get(f"/tags/{relay['id']}/value")).json()[
                        "value_boolean"
                    ] is False
                    await set_value(input_a, "31")
                    await until(lambda: success(on, 2))
                    assert (await api.get(f"/tags/{relay['id']}/value")).json()[
                        "value_boolean"
                    ] is True
                    assert any(
                        e["type"] == "command_status"
                        and e["data"]["source"] == "automation"
                        and e["data"]["status"] == "SUCCESS"
                        for e in events
                    )
                    assert any(e["type"] == "tag_value" for e in events)
                    history = (await api.get(f"/tags/{relay['id']}/history")).json()
                    assert history["points"]
                    print(
                        "PASS: simulator FOR, ON/OFF rules, hysteresis, edge, verified automation commands, current/history/WebSocket",
                        flush=True,
                    )
                finally:
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
            both = await create(
                "/automation/rules",
                name="Both inputs",
                enabled=True,
                condition_mode="ALL",
                conditions=[
                    {"tag_id": input_a["id"], "operator": ">", "value": "30"},
                    {"tag_id": input_b["id"], "operator": ">=", "value": "80"},
                ],
                actions=[{"target_tag_id": relay["id"], "value": False}],
            )
            await asyncio.sleep(0.8)
            assert not await executions(both)
            await set_value(input_b, "81")
            await until(lambda: success(both))
            print("PASS: multi-condition ALL rule requires both inputs", flush=True)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="msedge", headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 390, "height": 844})
                    await browser_session(page, api)
                    await page.goto(f"http://localhost:{ui_port}/automation")
                    await page.get_by_text("Above threshold", exact=True).wait_for()
                    await page.get_by_role("button", name="Executions", exact=True).first.click()
                    await (
                        page.get_by_role("dialog")
                        .get_by_text("Commands:", exact=False)
                        .first.wait_for()
                    )
                    await page.get_by_role("button", name="Close", exact=True).click()
                    await page.get_by_role("button", name="Create rule", exact=True).click()
                    await page.get_by_role("button", name="Add condition", exact=True).click()
                    await page.get_by_role("button", name="Add action", exact=True).click()
                    await page.get_by_label("Rule name", exact=False).fill("Browser draft")
                    await page.get_by_role("button", name="Save rule", exact=True).click()
                    await page.get_by_text("Browser draft", exact=True).wait_for()
                    print(
                        "PASS: mobile Automation UI, editor, status and execution history",
                        flush=True,
                    )
                finally:
                    await browser.close()
            await compose("exec", "-T", "api", "alembic", "check")
            logs = await compose("logs", "--no-color", "api", "worker")
            assert '"level": "ERROR"' not in logs, logs[-8000:]
            print("PASS: Alembic metadata and clean API/worker logs", flush=True)
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Removed isolated automation project and fixtures", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
