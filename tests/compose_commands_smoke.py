"""Isolated simulator and software-only TCP command integration. No physical device access."""

import asyncio
import json
import os
import subprocess
from decimal import Decimal
from uuid import uuid4

import httpx
from compose_modbus_smoke import free_port
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect


async def main() -> None:
    project = f"modbus-commands-test-{uuid4().hex[:10]}"
    api_port, frontend_port, pg_port = free_port(), free_port(), free_port()
    origin = f"http://localhost:{frontend_port}"
    env = {
        **os.environ,
        "API_PORT": str(api_port),
        "FRONTEND_PORT": str(frontend_port),
        "POSTGRES_PORT": str(pg_port),
        "TELEMETRY_SOURCE": "simulator",
        "SIMULATOR_ENABLED": "false",
        "SIMULATOR_FAILURE_PROBABILITY": "0",
        "MODBUS_WRITES_ENABLED": "false",
        "CORS_ORIGINS": json.dumps([origin]),
        "WORKER_CONFIG_REFRESH_SECONDS": "0.2",
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

    async def compose(*args: str) -> str:
        result = await asyncio.to_thread(
            subprocess.run, [*prefix, *args], env=env, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError(f"Compose {args}: {result.stderr}")
        return result.stdout

    try:
        await compose("up", "-d", "--no-build", "--wait")
        async with httpx.AsyncClient(base_url=f"http://localhost:{api_port}", timeout=10) as api:

            async def create(resource, **data):
                response = await api.post(f"/api/{resource}", json=data)
                response.raise_for_status()
                return response.json()

            async def mode(expected):
                async with asyncio.timeout(20):
                    while (await api.get("/api/system/runtime")).json()["mode"] != expected:
                        await asyncio.sleep(0.2)

            async def completed(identifier):
                async with asyncio.timeout(20):
                    while True:
                        row = (await api.get(f"/api/commands/{identifier}")).json()
                        if row["status"] in ("SUCCESS", "FAILED", "EXPIRED", "CANCELLED"):
                            assert row["status"] == "SUCCESS", row
                            return row
                        await asyncio.sleep(0.1)

            await mode("simulator")
            connection = await create(
                "connections",
                name="Isolated software transport",
                protocol="modbus_tcp",
                host="modbus-test",
                port=5020,
            )
            device = await create(
                "devices", name="Software test device", connection_id=connection["id"], slave_id=7
            )
            coil = await create(
                "tags",
                name="Software coil",
                key="test_coil",
                device_id=device["id"],
                register_type="coil",
                address=10,
                data_type="bool",
                writable=True,
                history_enabled=True,
                poll_interval_ms=500,
            )
            numeric = await create(
                "tags",
                name="Software numeric",
                key="test_numeric",
                device_id=device["id"],
                register_type="holding_register",
                address=103,
                data_type="float32",
                writable=True,
                history_enabled=True,
                poll_interval_ms=500,
            )
            exact = await create(
                "tags",
                name="Software exact",
                key="test_exact",
                device_id=device["id"],
                register_type="holding_register",
                address=100,
                data_type="uint64",
                writable=True,
                poll_interval_ms=500,
            )
            await asyncio.sleep(1)
            async with connect(f"ws://localhost:{api_port}/api/ws/live") as ws:
                events = []

                async def receive():
                    async for raw in ws:
                        events.append(json.loads(raw))

                listener = asyncio.create_task(receive())
                try:
                    for tag, value in (
                        (coil, False),
                        (coil, True),
                        (numeric, "23.5"),
                        (exact, "18446744073709551615"),
                    ):
                        command = await create(
                            f"tags/{tag['id']}/commands", value=value, request_id=str(uuid4())
                        )
                        result = await completed(command["id"])
                        assert (
                            result["verified_value"] == value
                            if type(value) is bool
                            else Decimal(result["verified_value"]) == Decimal(value)
                        )
                        current = (await api.get(f"/api/tags/{tag['id']}/value")).json()
                        assert current["source"] == "simulator"
                        assert (
                            current["value_boolean"] == value
                            if type(value) is bool
                            else Decimal(current["value_numeric_exact"]) == Decimal(value)
                        )
                    await asyncio.sleep(1)
                    assert any(
                        e["type"] == "command_status" and e["data"]["status"] == "SUCCESS"
                        for e in events
                    )
                    assert any(e["type"] == "tag_value" for e in events)
                    history = (await api.get(f"/api/tags/{numeric['id']}/history")).json()
                    assert any(p["value_numeric"] == 23.5 for p in history["points"])
                    print(
                        "PASS: simulator coil OFF -> ON, numeric and exact uint64, current/history and shared WebSocket commands",
                        flush=True,
                    )
                finally:
                    listener.cancel()
                    await asyncio.gather(listener, return_exceptions=True)

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="msedge", headless=True)
                try:
                    page = await browser.new_page(viewport={"width": 390, "height": 844})
                    await page.goto(f"{origin}/tags/{numeric['id']}")
                    await page.get_by_label("Requested value", exact=True).fill("27.5")
                    await page.get_by_role("button", name="Apply", exact=True).click()
                    try:
                        await page.get_by_text("Verified: 27.5", exact=True).wait_for()
                    except Exception:
                        print(await page.locator('body').inner_text(), flush=True)
                        print((await api.get('/api/commands')).json(), flush=True)
                        raise
                    assert await page.get_by_text("Status: SUCCESS", exact=True).is_visible()
                    await page.goto(f"{origin}/commands")
                    await page.get_by_role("heading", name="Commands", exact=True).wait_for()
                    await page.get_by_role("cell", name="27.5", exact=True).first.wait_for()
                    assert await page.locator("body").evaluate("(e) => e.scrollWidth <= innerWidth")
                    print(
                        "PASS: actual mobile browser manual control and Commands page", flush=True
                    )
                finally:
                    await browser.close()

            # Only an isolated software server is reachable from these stored test connections.
            response = await api.patch(f"/api/tags/{exact['id']}", json={"enabled": False})
            response.raise_for_status()
            await compose("stop", "worker")
            env["TELEMETRY_SOURCE"] = "modbus"
            env["MODBUS_WRITES_ENABLED"] = "true"
            await compose("up", "-d", "--no-build", "--no-deps", "worker")
            await mode("modbus")
            await asyncio.sleep(1)
            for tag, value in ((coil, False), (coil, True), (numeric, "-12.5")):
                command = await create(
                    f"tags/{tag['id']}/commands", value=value, confirm_physical=True
                )
                result = await completed(command["id"])
                assert (
                    result["verified_value"] == value
                    if type(value) is bool
                    else Decimal(result["verified_value"]) == Decimal(value)
                )
                assert (await api.get(f"/api/tags/{tag['id']}/value")).json()[
                    "source"
                ] == "modbus_tcp"
            print(
                "PASS: software TCP coil and multi-register writes with actual PyModbus read-back; no hardware used",
                flush=True,
            )
            await compose("exec", "-T", "api", "alembic", "check")
            logs = await compose("logs", "--no-color", "api", "worker")
            assert '"level": "ERROR"' not in logs, logs[-6000:]
            print("PASS: migrations/metadata and API/worker logs", flush=True)
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Removed isolated command fixtures and database", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
