"""Opt-in live-stack verification. Creates and removes only its own configuration fixtures.

Run from repository root with simulation enabled on the running worker. The --restarts flag
also stops/restarts the development worker and PostgreSQL to verify stale/recovery behavior.
"""
import argparse
import asyncio
import json
import os
import subprocess
from uuid import uuid4

import httpx
from compose_auth_helpers import login_existing, ws_headers
from sqlalchemy import func, select
from websockets.asyncio.client import connect

from app.core.config import Settings
from app.db.session import Database
from app.models import TagCurrentValue


async def main(api_url: str, frontend_url: str, restarts: bool) -> None:
    created: list[tuple[str, int]] = []
    token = uuid4().hex[:10]
    database = Database(Settings())

    async def compose(*arguments: str, failure: str = "0") -> None:
        environment = {**os.environ, "SIMULATOR_ENABLED": "true",
                       "SIMULATOR_FAILURE_PROBABILITY": failure}
        result = await asyncio.to_thread(subprocess.run, ["docker", "compose", *arguments],
                                         env=environment, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"Compose operation failed: {arguments}: {result.stderr}")

    async with httpx.AsyncClient(base_url=api_url, timeout=10) as api:
        await login_existing(api)
        async def create(resource: str, **data):
            response = await api.post(f"/api/{resource}", json=data)
            response.raise_for_status()
            record = response.json()
            created.append((resource, record["id"]))
            return record

        async def wait_quality(identifier: int, quality: str, timeout: float = 45):
            async with asyncio.timeout(timeout):
                while True:
                    response = await api.get(f"/api/tags/{identifier}/value")
                    if response.status_code == 200 and response.json()["quality"] == quality:
                        return response.json()
                    await asyncio.sleep(0.2)

        async def next_value(socket, identifier: int, quality: str | None = None):
            async with asyncio.timeout(45):
                while True:
                    event = json.loads(await socket.recv())
                    if (event["type"] == "tag_value" and event["data"]["tag_id"] == identifier
                            and (quality is None or event["data"]["quality"] == quality)):
                        return event["data"]

        try:
            response = await api.get("/api/health/db")
            response.raise_for_status()
            connection = await create("connections", name=f"Smoke {token}", protocol="modbus_tcp", host="simulator.invalid")
            device = await create("devices", name=f"Smoke {token}", connection_id=connection["id"], slave_id=1)
            tags = []
            for index, data_type in enumerate(("bool", "uint16", "float32", "uint64")):
                tags.append(await create("tags", name=f"Smoke {token} {index}", key=f"smoke_{token}_{index}",
                                         device_id=device["id"], register_type="coil" if data_type == "bool" else "holding_register",
                                         address=0, data_type=data_type, poll_interval_ms=250))
            for tag in tags:
                await wait_quality(tag["id"], "GOOD")
            async with database.sessions() as session:
                count = await session.scalar(select(func.count()).select_from(TagCurrentValue)
                                              .where(TagCurrentValue.tag_id.in_([tag["id"] for tag in tags])))
                assert count == len(tags), count
            identifier = tags[1]["id"]
            ws_url = api_url.replace("http", "ws", 1) + "/api/ws/live"
            proxy_url = frontend_url.replace("http", "ws", 1) + "/api/ws/live"
            async with connect(ws_url, additional_headers=ws_headers(api)) as first, connect(proxy_url, origin=frontend_url, additional_headers=ws_headers(api)) as second:
                assert json.loads(await first.recv())["type"] == "ready"
                assert json.loads(await second.recv())["type"] == "ready"
                first_value = await next_value(first, identifier)
                second_value = await next_value(first, identifier)
                assert second_value["revision"] > first_value["revision"]
                assert second_value["value_numeric"] != first_value["value_numeric"]
                assert (await next_value(second, identifier))["quality"] == "GOOD"
                print("PASS: separate worker/API containers, PostgreSQL current rows, changing values, two WebSocket clients and frontend proxy", flush=True)
                if restarts:
                    await compose("stop", "worker")
                    stale = await wait_quality(identifier, "STALE")
                    assert stale["value_numeric"] is not None
                    assert (await next_value(first, identifier))["revision"] > first_value["revision"]
                    await compose("start", "worker")
                    await wait_quality(identifier, "GOOD")
                    print("PASS: stopped-worker stale detection and recovery", flush=True)
                    await compose("up", "-d", "--no-deps", "worker", failure="1")
                    failed = await wait_quality(identifier, "COMM_ERROR")
                    assert failed["value_numeric"] is not None and failed["source_timestamp"] is not None
                    await compose("up", "-d", "--no-deps", "worker")
                    await wait_quality(identifier, "GOOD")
                    print("PASS: injected communication failure preserves value and recovers", flush=True)
                    await compose("restart", "postgres")
                    async with asyncio.timeout(60):
                        while json.loads(await first.recv())["type"] != "resync_required":
                            pass
                    await wait_quality(identifier, "GOOD", timeout=60)
                    assert (await next_value(first, identifier, quality="GOOD"))["quality"] == "GOOD"
                    print("PASS: PostgreSQL interruption, LISTEN reconnect/resync and continued live delivery", flush=True)
            await api.patch(f"/api/tags/{identifier}", json={"enabled": False})
            disabled = await wait_quality(identifier, "DISABLED")
            await asyncio.sleep(1)
            unchanged = (await api.get(f"/api/tags/{identifier}/value")).json()
            assert unchanged["revision"] == disabled["revision"]
            print("PASS: configuration refresh and disabled tag stops acquisition", flush=True)
        finally:
            if restarts:
                await compose("up", "-d", "--no-deps", "worker")
            for resource, identifier in reversed(created):
                response = await api.delete(f"/api/{resource}/{identifier}")
                response.raise_for_status()
            await database.close()
            print("Smoke fixtures removed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--frontend-url", default="http://localhost:5173")
    parser.add_argument("--restarts", action="store_true")
    options = parser.parse_args()
    asyncio.run(main(options.api_url, options.frontend_url, options.restarts))
