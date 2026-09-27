"""Dashboard integration: disposable simulator Compose project; no physical I/O/Telegram."""

import asyncio
import json
import os
import subprocess
from uuid import uuid4

import httpx
from compose_auth_helpers import bootstrap_login, browser_session
from compose_modbus_smoke import free_port
from playwright.async_api import async_playwright


async def main() -> None:
    project = f"modbus-dashboard-test-{uuid4().hex[:10]}"
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
                response = await api.post(path, json=values)
                response.raise_for_status()
                return response.json()

            async def until(check, timeout=30):
                async with asyncio.timeout(timeout):
                    while True:
                        result = await check()
                        if result:
                            return result
                        await asyncio.sleep(0.2)

            async def ready():
                row = (await api.get("/system/runtime")).json()
                return row["mode"] == "simulator" and row["alive"]

            await until(ready)
            connection = await create(
                "/connections",
                name="Dashboard isolated transport",
                protocol="modbus_tcp",
                host="unused.invalid",
            )
            device = await create(
                "/devices", name="Dashboard simulator", connection_id=connection["id"], slave_id=1
            )

            async def tag(key, dtype, address, unit=None):
                return await create(
                    "/tags",
                    name=key,
                    key=key,
                    device_id=device["id"],
                    register_type="coil" if dtype == "bool" else "holding_register",
                    data_type=dtype,
                    address=address,
                    writable=True,
                    poll_interval_ms=300,
                    history_enabled=True,
                    unit=unit,
                )

            temperature = await tag("test_temperature", "float32", 0, "C")
            humidity = await tag("test_humidity", "float32", 2, "%")
            relay = await tag("test_relay", "bool", 0)

            async def completed(identifier):
                row = (await api.get(f"/commands/{identifier}")).json()
                assert row["status"] not in ("FAILED", "CANCELLED", "EXPIRED"), row
                return row if row["status"] == "SUCCESS" else None

            command = await create(f"/tags/{relay['id']}/commands", value=False)
            await until(lambda: completed(command["id"]))
            board = await create(
                "/dashboards",
                name="Integration dashboard",
                slug="integration-dashboard",
                is_default=True,
            )
            configs = [
                ("value", "Temperature value", [temperature["id"]], {}),
                ("gauge", "Humidity gauge", [humidity["id"]], {"min": 0, "max": 100}),
                ("chart", "Temperature history", [temperature["id"]], {}),
                ("boolean", "Relay status", [relay["id"]], {}),
                ("switch", "Relay control", [relay["id"]], {}),
                ("alarms", "Active alarms", [], {"severities": ["CRITICAL"]}),
                ("setpoint", "Numeric control", [temperature["id"]], {}),
                ("text", "Instructions", [], {"text": "Disposable simulator test"}),
            ]
            for index, (kind, title, ids, config) in enumerate(configs):
                layouts = [
                    {"breakpoint": b, "x": 0, "y": index * 12, "w": w, "h": 12}
                    for b, w in (("lg", 6), ("md", 6), ("sm", 1))
                ]
                await create(
                    f"/dashboards/{board['id']}/widgets",
                    type=kind,
                    title=title,
                    tag_ids=ids,
                    configuration=config,
                    layouts=layouts,
                )

            async def values_ready():
                rows = (await api.get("/tags/values")).json()
                return len(rows) == 3 and all(v["quality"] == "GOOD" for v in rows)

            await until(values_ready)
            await create(
                "/alarms/rules",
                name="Dashboard test alarm",
                tag_id=temperature["id"],
                operator=">",
                value="-100",
                severity="CRITICAL",
                enabled=True,
                notification_enabled=False,
            )

            async def alarm_ready():
                rows = (await api.get("/alarms/events?active=true")).json()
                return rows[0] if rows else None

            await until(alarm_ready)
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(channel="msedge", headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                    await browser_session(page, api)
                    errors = []
                    sockets = []
                    events = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def socket_open(socket):
                        if "/api/ws/live" in socket.url:
                            sockets.append(socket.url)

                            def frame(payload):
                                event = json.loads(payload)
                                events.append(event)

                            socket.on("framereceived", frame)

                    page.on("websocket", socket_open)
                    await page.goto(f"http://localhost:{ui_port}/dashboard")
                    await page.get_by_role(
                        "heading", name="Temperature value", exact=True
                    ).wait_for()
                    await page.get_by_role("img", name="Historical line chart").wait_for()
                    await page.get_by_role("progressbar", name="Humidity gauge gauge").wait_for()
                    await page.get_by_text("CRITICAL: Dashboard test alarm", exact=True).wait_for()

                    async def live_changed():
                        versions = {
                            e["data"]["revision"]
                            for e in events
                            if e["type"] == "tag_value" and e["data"]["tag_id"] == temperature["id"]
                        }
                        return len(versions) >= 2

                    await until(live_changed)
                    assert len(sockets) == 1, sockets
                    control = page.locator(".react-grid-item").filter(
                        has=page.get_by_role("heading", name="Relay control", exact=True)
                    )
                    await control.get_by_role("combobox", name="Requested state").click()
                    await page.get_by_role("option", name="ON", exact=True).click()
                    await control.get_by_role("button", name="Apply", exact=True).click()
                    await page.get_by_role("button", name="Confirm write", exact=True).click()
                    await control.get_by_text("Status: SUCCESS", exact=True).wait_for()
                    await control.get_by_text("Verified: ON", exact=True).wait_for()
                    await page.get_by_role("button", name="Acknowledge", exact=True).click()
                    await page.get_by_text("test_temperature - ACKNOWLEDGED", exact=True).wait_for()
                    chart_card = page.locator(".react-grid-item").filter(
                        has=page.get_by_role("heading", name="Temperature history", exact=True)
                    )
                    await chart_card.get_by_role("combobox", name="Chart range").click()
                    await page.get_by_role("option", name="6 hours", exact=True).click()
                    await chart_card.get_by_role(
                        "img", name="Historical line chart", exact=True
                    ).wait_for()
                    await page.get_by_role(
                        "button", name="Edit dashboard layout", exact=True
                    ).click()
                    assert await control.get_by_text(
                        "Controls are unavailable while editing the dashboard.", exact=True
                    ).is_visible()
                    first = page.locator(".react-grid-item").first
                    handle = first.locator(".react-resizable-handle")
                    await handle.scroll_into_view_if_needed()
                    bounds = await handle.bounding_box()
                    assert bounds
                    await page.mouse.move(
                        bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
                    )
                    await page.mouse.down()
                    await page.mouse.move(bounds["x"] + 80, bounds["y"] + 100, steps=10)
                    await page.mouse.up()
                    await page.get_by_text("Unsaved layout changes", exact=True).wait_for()
                    await page.get_by_role("button", name="Save layout", exact=True).click()
                    await page.get_by_text("Layout saved", exact=True).wait_for()
                    await page.get_by_role("button", name="Finish editing", exact=True).click()
                    saved = (await api.get(f"/dashboards/{board['id']}")).json()
                    assert any(
                        layout["breakpoint"] == "lg" and (layout["w"] != 6 or layout["h"] != 12)
                        for layout in saved["widgets"][0]["layouts"]
                    ), saved["widgets"][0]["layouts"]
                    await page.set_viewport_size({"width": 390, "height": 844})
                    await page.reload()
                    await page.get_by_role(
                        "heading", name="Temperature value", exact=True
                    ).wait_for()
                    assert await page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    rectangles = await page.locator(".react-grid-item").evaluate_all(
                        "(items) => items.map(e => ({x:e.getBoundingClientRect().left,w:e.getBoundingClientRect().width}))"
                    )
                    assert all(r["x"] >= 0 and r["x"] + r["w"] <= 391 for r in rectangles), (
                        rectangles
                    )
                    assert (await api.get(f"/dashboards/{board['id']}")).json()["widgets"] == saved[
                        "widgets"
                    ]
                    assert any(
                        e["type"] == "command_status" and e["data"]["status"] == "SUCCESS"
                        for e in events
                    )
                    assert any(
                        e["type"] == "alarm_event" and e["data"]["state"] == "ACKNOWLEDGED"
                        for e in events
                    )
                    assert not errors, errors
                    print(
                        "PASS: eight widgets, live shared socket, history chart/range, simulator command/read-back, alarm acknowledgement, resize/save, reload, mobile width",
                        flush=True,
                    )
                except Exception:
                    print("Browser errors:", errors, flush=True)
                    print(
                        "Dashboard text:",
                        (await page.locator("body").inner_text())[:12000],
                        flush=True,
                    )
                    raise
                finally:
                    await browser.close()
            await compose("restart", "api", "worker", "frontend")
            await compose("up", "-d", "--no-build", "--wait")
            await until(ready)
            assert (await api.get(f"/dashboards/{board['id']}")).json()["widgets"] == saved[
                "widgets"
            ]
            assert (await api.get(f"/tags/{temperature['id']}/history")).json()["count"] > 0
            await compose("exec", "-T", "api", "alembic", "check")
            logs = await compose("logs", "--no-color", "api", "worker")
            assert '"level": "ERROR"' not in logs, logs[-6000:]
            print(
                "PASS: restart persistence, historical records, Alembic check and clean API/worker logs",
                flush=True,
            )
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Removed isolated dashboard project and fixtures", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
