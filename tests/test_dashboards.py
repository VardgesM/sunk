from copy import deepcopy

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.models import Dashboard, DashboardWidgetLayout, Tag
from tests.test_configuration import create, setup_tag

pytestmark = pytest.mark.anyio


def widget(bindings=None, **overrides):
    return {
        "type": "value",
        "title": "Reading",
        "configuration": {},
        "tag_ids": bindings or [],
        "layouts": [
            {"breakpoint": b, "x": 0, "y": 0, "w": w, "h": 6}
            for b, w in (("lg", 4), ("md", 3), ("sm", 1))
        ],
        **overrides,
    }


async def dashboard(api, **overrides):
    return await create(api, "dashboards", **{"name": "Overview", "slug": "overview", **overrides})


async def test_dashboard_crud_default_and_unique_slug(api):
    first = await dashboard(api, is_default=True)
    second = await dashboard(api, slug="second", is_default=True)
    rows = (await api.get("/api/dashboards")).json()
    assert [r["id"] for r in rows if r["is_default"]] == [second["id"]]
    assert (
        await api.post("/api/dashboards", json={"name": "Duplicate", "slug": "second"})
    ).status_code == 409
    updated = await api.patch(
        f"/api/dashboards/{first['id']}", json={"name": "Renamed", "is_default": True}
    )
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["revision"] > first["revision"]
    assert (await api.get(f"/api/dashboards/{second['id']}")).json()["is_default"] is False
    assert (await api.delete(f"/api/dashboards/{first['id']}")).status_code == 204
    assert (await api.get(f"/api/dashboards/{first['id']}")).status_code == 404


async def test_widget_crud_and_safe_deletion(api, database_sessions):
    tag = await setup_tag(api)
    board = await dashboard(api)
    row = await create(api, f"dashboards/{board['id']}/widgets", **widget([tag["id"]]))
    assert row["configuration"]["decimals"] == 2
    changed = await api.patch(
        f"/api/dashboard-widgets/{row['id']}",
        json={"title": "Updated", "configuration": {"decimals": 4}},
    )
    assert changed.status_code == 200
    assert changed.json()["configuration"]["decimals"] == 4
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409
    assert (await api.delete(f"/api/dashboards/{board['id']}")).status_code == 204
    async with database_sessions() as session:
        assert await session.get(Tag, tag["id"]) is not None
        assert await session.scalar(select(DashboardWidgetLayout)) is None
    assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 204


@pytest.mark.parametrize(
    "kind", ["value", "gauge", "chart", "boolean", "switch", "setpoint", "alarms", "text"]
)
async def test_all_widget_types(api, kind):
    tag = await setup_tag(
        api,
        data_type="bool" if kind in ("boolean", "switch") else "float32",
        register_type="coil" if kind in ("boolean", "switch") else "holding_register",
        writable=True,
    )
    board = await dashboard(api)
    result = await api.post(
        f"/api/dashboards/{board['id']}/widgets",
        json=widget([] if kind in ("alarms", "text") else [tag["id"]], type=kind),
    )
    assert result.status_code == 201, result.text
    assert (await api.delete(f"/api/dashboard-widgets/{result.json()['id']}")).status_code == 204


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "script"},
        {"tag_ids": []},
        {"tag_ids": [999]},
        {"configuration": {"javascript": "alert(1)"}},
        {"configuration": {"decimals": -1}},
        {"type": "gauge", "configuration": {"min": 100, "max": 0}},
        {"type": "gauge", "configuration": {"warning_threshold": 150}},
        {"type": "chart", "configuration": {"refresh_seconds": 1}},
        {"type": "chart", "configuration": {"range_hours": 0}},
        {"type": "text", "tag_ids": [1]},
        {"layouts": []},
        {"title": " "},
    ],
)
async def test_invalid_widget_configuration(api, changes):
    tag = await setup_tag(api)
    board = await dashboard(api)
    result = await api.post(
        f"/api/dashboards/{board['id']}/widgets", json=widget([tag["id"]], **changes)
    )
    assert result.status_code == 422, result.text


@pytest.mark.parametrize(
    "kind,overrides",
    [
        ("gauge", {"data_type": "bool", "register_type": "coil"}),
        ("boolean", {}),
        ("switch", {}),
        ("setpoint", {}),
        (
            "switch",
            {"data_type": "bool", "register_type": "coil", "writable": True, "enabled": False},
        ),
        ("setpoint", {"register_type": "input_register"}),
    ],
)
async def test_incompatible_tags(api, kind, overrides):
    tag = await setup_tag(api, **overrides)
    board = await dashboard(api)
    assert (
        await api.post(
            f"/api/dashboards/{board['id']}/widgets", json=widget([tag["id"]], type=kind)
        )
    ).status_code == 422


async def test_multitag_chart_and_merged_patch(api):
    first = await setup_tag(api, key="one", unit="C")
    second = await setup_tag(api, key="two", unit="C")
    board = await dashboard(api)
    row = await create(
        api,
        f"dashboards/{board['id']}/widgets",
        **widget([second["id"], first["id"]], type="chart"),
    )
    assert row["tag_ids"] == [second["id"], first["id"]]
    assert (
        await api.patch(f"/api/dashboard-widgets/{row['id']}", json={"type": "value"})
    ).status_code == 422
    assert (
        await api.post(
            f"/api/dashboards/{board['id']}/widgets",
            json=widget([first["id"], first["id"]], type="chart"),
        )
    ).status_code == 422
    await api.patch(f"/api/tags/{second['id']}", json={"unit": "%"})
    assert (
        await api.post(
            f"/api/dashboards/{board['id']}/widgets",
            json=widget([first["id"], second["id"]], type="chart"),
        )
    ).status_code == 422


async def test_layout_persistence_conflict_and_cross_dashboard(api):
    board = await dashboard(api)
    row = await create(api, f"dashboards/{board['id']}/widgets", **widget(type="text"))
    board = (await api.get(f"/api/dashboards/{board['id']}")).json()
    layouts = [{**layout, "widget_id": row["id"], "y": 12} for layout in row["layouts"]]
    url = f"/api/dashboards/{board['id']}/layout"
    payload = {"revision": board["revision"], "layouts": layouts}
    saved = await api.patch(url, json=payload)
    assert saved.status_code == 200, saved.text
    assert all(layout["y"] == 12 for layout in saved.json()["widgets"][0]["layouts"])
    assert (await api.patch(url, json=payload)).status_code == 409
    payload["revision"] = saved.json()["revision"]
    bad = deepcopy(payload)
    bad["layouts"][0]["widget_id"] = 999
    assert (await api.patch(url, json=bad)).status_code == 422
    bad = deepcopy(payload)
    bad["layouts"][2]["w"] = 2
    assert (await api.patch(url, json=bad)).status_code == 422
    bad = deepcopy(payload)
    bad["layouts"][2] = bad["layouts"][0]
    assert (await api.patch(url, json=bad)).status_code == 422
    assert (await api.get(f"/api/dashboards/{board['id']}")).json()["widgets"][0][
        "layouts"
    ] == saved.json()["widgets"][0]["layouts"]


async def test_database_default_constraint(database_sessions):
    async with database_sessions() as session:
        session.add(Dashboard(name="One", slug="one", is_default=True))
        await session.commit()
        with pytest.raises(IntegrityError):
            await session.execute(insert(Dashboard).values(name="Two", slug="two", is_default=True))
        await session.rollback()
