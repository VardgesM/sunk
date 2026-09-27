"""Phase 8 integration in a disposable simulator-only Compose project. No physical I/O."""

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
    project = f"modbus-alarms-test-{uuid4().hex[:10]}"
    api_port, ui_port, pg_port = free_port(), free_port(), free_port()
    env = {
        **os.environ,
        "AUTH_COOKIE_SECURE": "false",
        "API_PORT": str(api_port),
        "FRONTEND_PORT": str(ui_port),
        "POSTGRES_PORT": str(pg_port),
        "TELEMETRY_SOURCE": "simulator",
        "SIMULATOR_ENABLED": "false",
        "TELEGRAM_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
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
            await set_value(relay, False)
            alarm = await create(
                "/alarms/rules",
                name="Numeric alarm",
                tag_id=input_a["id"],
                operator=">",
                value="30",
                hysteresis="2",
                for_duration_ms=1500,
                severity="CRITICAL",
                enabled=True,
                notification_enabled=True,
            )
            boolean = await create(
                "/alarms/rules",
                name="Boolean alarm",
                tag_id=relay["id"],
                operator="==",
                value=True,
                severity="INFO",
                enabled=True,
            )

            async def rows(rule):
                return (await api.get(f"/alarms/events?rule_id={rule['id']}")).json()

            async def state(rule, expected):
                values = await rows(rule)
                return values[0] if values and values[0]["state"] == expected else None

            messages = []
            async with connect(
                f"ws://localhost:{api_port}/api/ws/live", additional_headers=ws_headers(api)
            ) as ws:

                async def receive():
                    async for message in ws:
                        messages.append(json.loads(message))

                listener = asyncio.create_task(receive())
                try:
                    await set_value(input_a, "31")
                    await asyncio.sleep(0.4)
                    assert not await rows(alarm), "FOR fired too early"
                    event = await until(lambda: state(alarm, "ACTIVE"))
                    await asyncio.sleep(0.5)
                    assert len(await rows(alarm)) == 1
                    async with async_playwright() as pw:
                        browser = await pw.chromium.launch(channel="msedge", headless=True)
                        try:
                            page = await browser.new_page(viewport={"width": 390, "height": 844})
                            await browser_session(page, api)
                            await page.goto(f"http://localhost:{ui_port}/alarms")
                            await page.get_by_text("Numeric alarm", exact=True).wait_for()
                            await page.get_by_role("button", name="Acknowledge", exact=True).click()
                            await page.get_by_text("ACKNOWLEDGED", exact=True).wait_for()
                            await page.get_by_role("tab", name="Alarm rules", exact=True).click()
                            await page.get_by_role(
                                "button", name="New alarm rule", exact=True
                            ).click()
                            await page.get_by_label("Name", exact=False).fill("Browser alarm draft")
                            await page.get_by_role("button", name="Save", exact=True).click()
                            await page.get_by_text("Browser alarm draft", exact=False).wait_for()
                            assert await page.evaluate(
                                "document.documentElement.scrollWidth <= window.innerWidth"
                            )
                            print(
                                "PASS: mobile alarm UI, acknowledgement, rule editor, shell indicator",
                                flush=True,
                            )
                        finally:
                            await browser.close()
                    assert await state(alarm, "ACKNOWLEDGED")
                    await set_value(input_a, "29")
                    await asyncio.sleep(0.5)
                    assert await state(alarm, "ACKNOWLEDGED")
                    await set_value(input_a, "28")
                    await until(lambda: state(alarm, "CLEARED"))
                    assert (
                        await api.post(f"/alarms/events/{event['id']}/acknowledge")
                    ).status_code == 409
                    await set_value(input_a, "32")
                    await until(lambda: state(alarm, "ACTIVE"))
                    assert len(await rows(alarm)) == 2
                    await set_value(relay, True)
                    await until(lambda: state(boolean, "ACTIVE"))
                    await set_value(relay, False)
                    await until(lambda: state(boolean, "CLEARED"))
                    await asyncio.sleep(0.5)
                    states = {m["data"]["state"] for m in messages if m["type"] == "alarm_event"}
                    assert states == {"ACTIVE", "ACKNOWLEDGED", "CLEARED"}, states
                    assert any(m["type"] == "tag_value" for m in messages)
                    deliveries = (await api.get("/notifications/telegram/deliveries")).json()
                    assert len(deliveries) == 2 and all(
                        d["status"] == "SKIPPED" for d in deliveries
                    )
                    assert (await api.get(f"/tags/{input_a['id']}/history")).json()["points"]
                    await api.patch("/notifications/telegram/destination", json={"chat_id": "123"})
                    test = await create("/notifications/telegram/test")
                    await asyncio.sleep(1)
                    test_result = (await api.get("/notifications/telegram/deliveries")).json()[0]
                    assert test_result["id"] == test["id"] and test_result["status"] == "SKIPPED"
                    print(
                        "PASS: simulator numeric/boolean, FOR, hysteresis, lifecycle/reactivation, PostgreSQL NOTIFY/WebSocket, history, Telegram disabled/no duplicate delivery",
                        flush=True,
                    )
                finally:
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)
            await compose("exec", "-T", "api", "alembic", "check")
            logs = await compose("logs", "--no-color", "api", "worker")
            assert '"level": "ERROR"' not in logs, logs[-8000:]
            print("PASS: Alembic metadata and clean API/worker logs", flush=True)
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Removed isolated alarms project and fixtures", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
