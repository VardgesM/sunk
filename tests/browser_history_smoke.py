"""Opt-in Phase 4 PostgreSQL/API/worker/Edge integration; removes only owned fixtures."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from playwright.async_api import async_playwright
from sqlalchemy import delete, func, select
from websockets.asyncio.client import connect

from app.core.config import Settings
from app.db.session import Database
from app.models import TagHistory


async def main() -> None:
    token = uuid4().hex[:10]
    created: list[tuple[str, int]] = []
    database = Database(Settings())
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=15) as api:

        async def create(resource: str, **data: Any) -> dict:
            response = await api.post(f"/api/{resource}", json=data)
            response.raise_for_status()
            result = response.json()
            created.append((resource, result["id"]))
            return result

        async def history(identifier: int, **params: Any) -> dict:
            response = await api.get(f"/api/tags/{identifier}/history", params=params)
            response.raise_for_status()
            return response.json()

        async def patch(identifier: int, **values: Any) -> None:
            response = await api.patch(f"/api/tags/{identifier}", json=values)
            response.raise_for_status()

        async def wait_points(identifier: int, count: int) -> dict:
            async with asyncio.timeout(30):
                while True:
                    result = await history(identifier)
                    if result["total_count"] >= count:
                        return result
                    await asyncio.sleep(0.25)

        try:
            transport = await create(
                "connections",
                name=f"History {token}",
                protocol="modbus_tcp",
                host="simulator.invalid",
            )
            device = await create(
                "devices", name=f"History {token}", connection_id=transport["id"], slave_id=1
            )
            numeric = await create(
                "tags",
                name=f"Numeric {token}",
                key=f"history_{token}",
                device_id=device["id"],
                register_type="holding_register",
                address=0,
                data_type="float32",
                poll_interval_ms=250,
                history_enabled=True,
                history_mode="fixed_interval",
                history_interval_ms=1000,
            )
            boolean = await create(
                "tags",
                name=f"Boolean {token}",
                key=f"boolean_{token}",
                device_id=device["id"],
                register_type="coil",
                address=0,
                data_type="bool",
                poll_interval_ms=250,
                history_enabled=True,
                history_mode="on_change",
            )
            result = await wait_points(numeric["id"], 4)
            assert len({p["value_numeric"] for p in result["points"]}) > 1
            times = [
                datetime.fromisoformat(p["recorded_at"])
                for p in result["points"]
                if p["quality"] == "GOOD"
            ]
            assert all(
                (later - earlier).total_seconds() >= 1 for earlier, later in zip(times, times[1:])
            )
            async with database.sessions() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TagHistory)
                        .where(TagHistory.tag_id == numeric["id"])
                    )
                    >= 4
                )
            bool_history = await wait_points(boolean["id"], 3)
            states = [p["value_boolean"] for p in bool_history["points"] if p["quality"] == "GOOD"]
            assert all(a != b for a, b in zip(states, states[1:]))
            async with connect(
                "ws://localhost:5173/api/ws/live", origin="http://localhost:5173"
            ) as socket:
                revisions = []
                async with asyncio.timeout(10):
                    while len(revisions) < 3:
                        event = json.loads(await socket.recv())
                        if (
                            event["type"] == "tag_value"
                            and event["data"]["tag_id"] == numeric["id"]
                        ):
                            revisions.append(event["data"]["revision"])
                assert revisions == sorted(set(revisions))
            end = datetime.now(UTC) + timedelta(seconds=1)
            reduced = await history(
                numeric["id"],
                **{
                    "from": (times[0] - timedelta(seconds=0.1)).isoformat(),
                    "to": end.isoformat(),
                    "max_points": 2,
                },
            )
            assert reduced["downsampled"] and reduced["count"] <= 2
            assert all(
                p["minimum"] <= p["average"] <= p["maximum"]
                for p in reduced["points"]
                if p["average"] is not None
            )
            print(
                "PASS: fixed-interval numeric history, boolean on-change, PostgreSQL SQL buckets, independent WebSocket updates",
                flush=True,
            )

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="msedge", headless=True)
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto(f"http://localhost:5173/tags/{numeric['id']}")
                await page.get_by_text("Live", exact=True).wait_for(timeout=15000)
                await page.get_by_role(
                    "img", name=f"Numeric {token} numeric line history chart"
                ).wait_for()
                assert await page.locator("svg path").count() > 0
                value = (
                    page.locator("dt")
                    .filter(has_text="Current value")
                    .locator("xpath=following-sibling::dd[1]")
                )
                initial = await value.inner_text()
                requests: list[str] = []
                page.on(
                    "request",
                    lambda request: (
                        requests.append(request.url) if "/history?" in request.url else None
                    ),
                )
                async with asyncio.timeout(10):
                    while await value.inner_text() == initial:
                        await asyncio.sleep(0.2)
                assert not requests, "Live values must not refetch historical charts"
                await page.get_by_role("combobox", name="Time range").click()
                await page.get_by_role("option", name="6 hours", exact=True).click()
                await page.get_by_role("button", name="Refresh history").click()
                await page.get_by_role("combobox", name="Time range").click()
                await page.get_by_role("option", name="Custom", exact=True).click()
                local = await page.evaluate(
                    "() => { const end = new Date(); const start = new Date(end - 3600000); const format = d => new Date(d - d.getTimezoneOffset()*60000).toISOString().slice(0,16); return [format(start), format(new Date(end.getTime()+60000))]; }"
                )
                await page.get_by_label("Start (local time)").fill(local[0])
                await page.get_by_label("End (local time)").fill(local[1])
                await page.get_by_role("button", name="Apply / Refresh").click()
                await page.get_by_role("img").wait_for()
                for width in (375, 768, 1024):
                    await page.set_viewport_size({"width": width, "height": 812})
                    try:
                        # ECharts responds through ResizeObserver on the next render frame.
                        await page.wait_for_function(
                            "document.documentElement.scrollWidth <= window.innerWidth",
                            timeout=5000,
                        )
                    except Exception:
                        print(
                            await page.evaluate(
                                "() => [...document.querySelectorAll('main *')].filter(e => e.getBoundingClientRect().right > innerWidth).map(e => ({tag:e.tagName, cls:e.className, width:e.getBoundingClientRect().width})).slice(0,15)"
                            ),
                            flush=True,
                        )
                        raise
                await page.goto(f"http://localhost:5173/tags/{boolean['id']}")
                await page.get_by_role(
                    "img", name=f"Boolean {token} boolean step history chart"
                ).wait_for()
                assert not errors, errors
                await browser.close()
            print(
                "PASS: actual ECharts SVG numeric/boolean charts, presets/custom ranges, mobile width, live values independent of history REST",
                flush=True,
            )

            await patch(numeric["id"], history_enabled=False)
            count = (await history(numeric["id"]))["total_count"]
            await asyncio.sleep(2.5)
            assert (await history(numeric["id"]))["total_count"] == count
            await patch(
                numeric["id"],
                history_enabled=True,
                history_mode="on_change",
                history_change_threshold=1000,
            )
            await asyncio.sleep(2.5)
            assert (await history(numeric["id"]))["total_count"] == count
            await patch(numeric["id"], history_change_threshold=0)
            await wait_points(numeric["id"], count + 3)
            assert (await api.delete(f"/api/tags/{numeric['id']}")).status_code == 409
            print(
                "PASS: disabled history stops inserts, numeric on-change threshold/reconfiguration, safe tag deletion",
                flush=True,
            )
        finally:
            for resource, identifier in reversed(created):
                if resource == "tags":
                    await patch(identifier, enabled=False, history_enabled=False)
                    async with database.sessions() as session, session.begin():
                        await session.execute(
                            delete(TagHistory).where(TagHistory.tag_id == identifier)
                        )
                response = await api.delete(f"/api/{resource}/{identifier}")
                response.raise_for_status()
            await database.close()
            print("Owned history/browser fixtures removed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
