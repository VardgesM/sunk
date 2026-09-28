"""Accelerated history backlog on disposable simulator databases only."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx


async def verify_backlog(edge, cloud, device, compose, create, rows, until):
    tags = []
    for index in range(24):
        tags.append(
            await create(
                edge,
                "tags",
                name=f"Backlog {index}",
                key=f"backlog_{index}",
                device_id=device["id"],
                register_type="holding_register",
                address=100 + index * 2,
                data_type="float32",
                poll_interval_ms=2000,
                history_enabled=True,
                history_mode="fixed_interval",
                history_interval_ms=60000,
            )
        )

    async def mirrored():
        found = [t for t in await rows(cloud, "tags") if t["name"].startswith("Backlog ")]
        return found if len(found) == 24 else None

    mirrored_tags = await until(mirrored)
    await compose("stop", "cloud-api")
    # Real simulator continues collecting offline. Accelerate only historical fixture
    # volume (100 already-selected points per tag) rather than waiting 100 minutes.
    await asyncio.sleep(5)
    ids = [t["id"] for t in tags]
    script = f"""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from app.core.config import Settings
from app.db.session import Database
from app.models import TagHistory
async def main():
 db=Database(Settings())
 start=datetime.now(UTC)-timedelta(hours=3)
 async with db.sessions() as s,s.begin():
  await s.execute(insert(TagHistory), [dict(tag_id=t,value_numeric=n,quality="GOOD",source="simulator",recorded_at=start+timedelta(minutes=n),source_timestamp=start+timedelta(minutes=n)) for t in {ids!r} for n in range(100)])
 await db.close()
asyncio.run(main())
"""
    await compose("exec", "-T", "edge-api", "python", "-c", script)
    pending = await rows(edge, "sync/status")
    assert pending["pending_history"] >= 2400
    assert pending["pending_current"] <= len(await rows(edge, "tags"))
    # Stop only the disposable worker so the exact final history set can be compared.
    await compose("stop", "edge-worker")
    await compose("start", "cloud-api")

    async def healthy():
        try:
            return (await cloud.get("/api/health/db")).status_code == 200
        except httpx.HTTPError:
            return False

    await until(healthy)
    distinctive = 9876.125
    script = f'''
import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from app.core.config import Settings
from app.db.session import Database
from app.services.current_values import Reading,upsert_current
async def main():
 db=Database(Settings())
 async with db.sessions() as s,s.begin():
  await upsert_current(s,{ids[0]},reading=Reading(Decimal("{distinctive}"),datetime.now(UTC),source="simulator"))
 await db.close()
asyncio.run(main())
'''
    await compose("exec", "-T", "edge-api", "python", "-c", script)
    await compose("restart", "edge-sync")
    cloud_tag = next(t for t in mirrored_tags if t["name"] == tags[0]["name"])

    async def fresh():
        value = await rows(cloud, f"tags/{cloud_tag['id']}/value")
        return value.get("value_numeric") == distinctive and value["source"] == "simulator"

    await until(fresh, timeout=20)
    assert (await rows(edge, "sync/status"))["pending_history"] > 0
    print(
        "PASS: 24 Tags, 2400+ offline history records; newest current delivered while history still pending; sync restart safe"
    )

    async def empty():
        return (await rows(edge, "sync/status"))["pending"] == 0

    # Let the existing stale maintenance emit its one quality transition first.
    await asyncio.sleep(7)
    await until(empty, timeout=180)
    start = (datetime.now(UTC) - timedelta(hours=4)).isoformat()
    end = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    for tag in tags:
        mirrored_tag = next(t for t in mirrored_tags if t["name"] == tag["name"])
        params = {"from": start, "to": end, "limit": 1000}
        left = await edge.get(f"/api/tags/{tag['id']}/history", params=params)
        right = await cloud.get(f"/api/tags/{mirrored_tag['id']}/history", params=params)
        left.raise_for_status()
        right.raise_for_status()
        a, b = left.json(), right.json()
        assert a["total_count"] == b["total_count"] >= 101
        # Full points include original timestamps, source, typed values and quality.
        assert json.dumps(a["points"], sort_keys=True) == json.dumps(b["points"], sort_keys=True)
    print(
        "PASS: backlog zero; every Tag history matches Edge exactly, ordered timestamps and no duplicates"
    )
