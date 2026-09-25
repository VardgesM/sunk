"""Opt-in Edge/Playwright check against the running development stack.

Install the optional browser extra and Edge; this script creates and removes its own fixtures.
"""
import asyncio
from uuid import uuid4

import httpx
from playwright.async_api import async_playwright


async def main() -> None:
    token = uuid4().hex[:10]
    name = f"Browser smoke {token}"
    created: list[tuple[str, int]] = []
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10) as api:
        async def create(resource: str, **data):
            response = await api.post(f"/api/{resource}", json=data)
            response.raise_for_status()
            record = response.json()
            created.append((resource, record["id"]))
            return record

        try:
            connection = await create("connections", name=name, protocol="modbus_tcp", host="simulator.invalid")
            device = await create("devices", name=name, connection_id=connection["id"], slave_id=1)
            await create("tags", name=name, key=f"browser_{token}", device_id=device["id"],
                         register_type="holding_register", address=0, data_type="float32", poll_interval_ms=250)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel="msedge", headless=True)
                page = await browser.new_page(viewport={"width": 1440, "height": 900})
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto("http://localhost:5173/tags")
                await page.get_by_label("Search name or key").fill(f"browser_{token}")
                await page.get_by_role("button", name="Apply", exact=True).click()
                await page.get_by_text("Live", exact=True).wait_for(timeout=15000)
                row = page.get_by_role("row").filter(has_text=f"browser_{token}")
                await row.get_by_text("GOOD", exact=True).wait_for(timeout=15000)
                cell = row.get_by_role("cell").nth(5)
                first = await cell.inner_text()
                await page.evaluate("window.__phase3_no_reload = true")
                async with asyncio.timeout(10):
                    while await cell.inner_text() == first:
                        await asyncio.sleep(0.2)
                assert await page.evaluate("window.__phase3_no_reload === true")
                print("PASS: actual browser snapshot, Live/GOOD display, changing values without reload", flush=True)
                await page.set_viewport_size({"width": 375, "height": 812})
                assert await page.get_by_role("button", name="Open navigation").is_visible()
                assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                await row.get_by_role("button", name=f"Edit {name}", exact=True).click()
                dialog = page.get_by_role("dialog")
                await dialog.wait_for(state="visible")
                bounds = await dialog.bounding_box()
                assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 375
                await dialog.get_by_role("button", name="Cancel", exact=True).click()
                assert not errors, errors
                print("PASS: 375px mobile navigation/form fit; no browser page errors", flush=True)
                await browser.close()
        finally:
            for resource, identifier in reversed(created):
                response = await api.delete(f"/api/{resource}/{identifier}")
                response.raise_for_status()
            print("Browser fixtures removed", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
