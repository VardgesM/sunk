"""Full read-only TCP integration in an isolated Compose project/database.

Requires built application images and the optional browser extra. Never changes the running
development project's source mode or configuration. Removes its own containers/volume on exit.
"""

import asyncio
import json
import os
import socket
import subprocess
from uuid import uuid4

import httpx
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def main() -> None:
    project = f"modbus-monitor-test-{uuid4().hex[:10]}"
    api_port, frontend_port, postgres_port = free_port(), free_port(), free_port()
    api_url, frontend_url = f"http://localhost:{api_port}", f"http://localhost:{frontend_port}"
    environment = {
        **os.environ,
        "API_PORT": str(api_port),
        "FRONTEND_PORT": str(frontend_port),
        "POSTGRES_PORT": str(postgres_port),
        "TELEMETRY_SOURCE": "modbus",
        "SIMULATOR_ENABLED": "false",
        "MODBUS_WRITES_ENABLED": "false",
        "CORS_ORIGINS": json.dumps([frontend_url]),
        "MODBUS_BACKOFF_MAX_SECONDS": "2",
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
            subprocess.run, [*prefix, *args], env=environment, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError(f"Compose {args} failed: {result.stderr}")
        return result.stdout

    try:
        await compose("config", "--quiet")
        await compose("up", "-d", "--no-build", "--wait")
        print(
            "PASS: isolated PostgreSQL/API/worker/frontend/Modbus test server started", flush=True
        )
        async with httpx.AsyncClient(base_url=api_url, timeout=10) as api:

            async def create(resource: str, **data) -> dict:
                response = await api.post(f"/api/{resource}", json=data)
                response.raise_for_status()
                return response.json()

            async def wait_quality(identifier: int, quality: str) -> dict:
                async with asyncio.timeout(30):
                    while True:
                        response = await api.get(f"/api/tags/{identifier}/value")
                        response.raise_for_status()
                        if response.json()["quality"] == quality:
                            return response.json()
                        await asyncio.sleep(0.2)

            async with asyncio.timeout(15):
                while (await api.get("/api/system/runtime")).json()["mode"] != "modbus":
                    await asyncio.sleep(0.2)
            connection = await create(
                "connections",
                name="Isolated software transport",
                protocol="modbus_tcp",
                host="modbus-test",
                port=5020,
                timeout_ms=500,
            )
            device = await create(
                "devices", name="Software slave", connection_id=connection["id"], slave_id=7
            )
            tags = []
            for index, (register, address, data_type, expected) in enumerate(
                [
                    ("holding_register", 100, "uint32", 305419896),
                    ("input_register", 200, "uint16", 7),
                    ("coil", 10, "bool", True),
                    ("discrete_input", 20, "bool", False),
                ]
            ):
                tag = await create(
                    "tags",
                    name=f"Protocol read {index}",
                    key=f"protocol_read_{index}",
                    device_id=device["id"],
                    register_type=register,
                    address=address,
                    data_type=data_type,
                    poll_interval_ms=250,
                    history_enabled=True,
                )
                tags.append(tag)
                current = await wait_quality(tag["id"], "GOOD")
                assert current["source"] == "modbus_tcp"
                assert (
                    current["value_boolean"] if data_type == "bool" else current["value_numeric"]
                ) == expected
            identifier = tags[0]["id"]
            async with connect(
                frontend_url.replace("http", "ws", 1) + "/api/ws/live", origin=frontend_url
            ) as ws:
                async with asyncio.timeout(10):
                    while True:
                        event = json.loads(await ws.recv())
                        if event["type"] == "tag_value" and event["data"]["tag_id"] == identifier:
                            assert event["data"]["source"] == "modbus_tcp"
                            break
            history = (await api.get(f"/api/tags/{identifier}/history")).json()
            assert history["count"] >= 2 and all(
                point["source"] == "modbus_tcp" for point in history["points"]
            )
            assert (await api.get(f"/api/devices/{device['id']}/status")).json()[
                "state"
            ] == "ONLINE"
            print(
                "PASS: four function codes, slave addressing, typed values, history, source and WebSocket",
                flush=True,
            )

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="msedge", headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"{frontend_url}/tags/{identifier}")
                await page.get_by_text("Modbus — read only", exact=False).wait_for()
                assert await page.get_by_text("SIMULATION MODE", exact=False).count() == 0
                await page.get_by_role(
                    "img", name="Protocol read 0 numeric line history chart"
                ).wait_for()
                await page.goto(f"{frontend_url}/connections")
                await page.get_by_text("CONNECTED", exact=True).wait_for()
                await page.get_by_role("button", name="Test Isolated software transport").click()
                await page.get_by_text("SUCCEEDED:", exact=False).wait_for(timeout=15000)
                assert not errors, errors
                await browser.close()
            assert (await api.get("/api/system/serial-ports")).status_code == 200
            print(
                "PASS: real-mode indicator, ECharts, runtime status, worker transport test, serial discovery API",
                flush=True,
            )

            await compose("stop", "modbus-test")
            failed = await wait_quality(identifier, "COMM_ERROR")
            assert failed["value_numeric"] == 305419896 and failed["source"] == "modbus_tcp"
            await compose("start", "modbus-test")
            recovered = await wait_quality(identifier, "GOOD")
            assert recovered["revision"] > failed["revision"]
            print(
                "PASS: server stop yields COMM_ERROR retaining value; restart recovers automatically",
                flush=True,
            )
            # A transport edit causes a new client without a worker restart.
            (
                await api.patch(f"/api/connections/{connection['id']}", json={"port": 5021})
            ).raise_for_status()
            await wait_quality(identifier, "COMM_ERROR")
            (
                await api.patch(f"/api/connections/{connection['id']}", json={"port": 5020})
            ).raise_for_status()
            await wait_quality(identifier, "GOOD")
            (
                await api.patch(f"/api/devices/{device['id']}", json={"slave_id": 11})
            ).raise_for_status()
            async with asyncio.timeout(15):
                while (await api.get(f"/api/tags/{tags[1]['id']}/value")).json()[
                    "value_numeric"
                ] != 11:
                    await asyncio.sleep(0.2)
            (
                await api.patch(f"/api/connections/{connection['id']}", json={"enabled": False})
            ).raise_for_status()
            await wait_quality(identifier, "DISABLED")
            print("PASS: live transport/slave reconfiguration and disabled connection", flush=True)
            errors = await compose("logs", "--no-log-prefix", "api")
            assert '"level": "ERROR"' not in errors, (
                "Unexpected API errors during real TCP verification"
            )
            logs = await compose("logs", "--no-log-prefix", "worker")
            assert '"level": "ERROR"' not in logs, (
                "Unexpected worker errors (communication warnings are expected)"
            )
            print("PASS: API/worker logs contain no unexpected errors", flush=True)
    finally:
        await compose("down", "--volumes", "--remove-orphans")
        print("Isolated test project and its fixture database removed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
