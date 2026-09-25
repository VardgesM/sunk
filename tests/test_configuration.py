from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Connection, Device, Location, Tag

pytestmark = pytest.mark.anyio


async def create(api: AsyncClient, resource: str, **values: Any) -> dict[str, Any]:
    response = await api.post(f"/api/{resource}", json=values)
    assert response.status_code == 201, response.text
    return response.json()


async def setup_device(api: AsyncClient) -> dict[str, Any]:
    connection = await create(
        api,
        "connections",
        name="Test transport",
        protocol="modbus_tcp",
        host="test.local",
    )
    return await create(
        api, "devices", name="Test device", connection_id=connection["id"], slave_id=1
    )


async def setup_tag(api: AsyncClient, **overrides: Any) -> dict[str, Any]:
    device = await setup_device(api)
    values = dict(
        name="Test reading",
        key="test_reading",
        device_id=device["id"],
        register_type="holding_register",
        address=0,
        data_type="uint16",
    )
    values.update(overrides)
    return await create(api, "tags", **values)


async def test_complete_crud_and_dependency_safe_deletion(api: AsyncClient) -> None:
    location = await create(api, "locations", name="Parent")
    child = await create(api, "locations", name="Child", parent_id=location["id"])
    connection = await create(
        api, "connections", name="Transport", protocol="modbus_tcp", host="test.local"
    )
    assert connection["port"] == 502
    device = await create(
        api,
        "devices",
        name="Device",
        connection_id=connection["id"],
        location_id=child["id"],
        slave_id=1,
    )
    assert device["connection_protocol"] == "modbus_tcp"
    tag = await create(
        api,
        "tags",
        name="Reading",
        key="reading",
        device_id=device["id"],
        register_type="holding_register",
        address=0,
        data_type="float32",
    )
    assert tag["scale"] == 1 and tag["offset"] == 0
    for resource, record in [
        ("locations", location),
        ("connections", connection),
        ("devices", device),
        ("tags", tag),
    ]:
        response = await api.get(f"/api/{resource}/{record['id']}")
        assert response.status_code == 200
        assert response.json()["created_at"].endswith("+00:00")
        response = await api.patch(
            f"/api/{resource}/{record['id']}", json={"name": "Renamed"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"
        assert response.json()["updated_at"] >= record["updated_at"]
        assert (await api.get(f"/api/{resource}")).json()
    for resource, record in [
        ("locations", location),
        ("locations", child),
        ("connections", connection),
        ("devices", device),
    ]:
        assert (await api.delete(f"/api/{resource}/{record['id']}")).status_code == 409
    for resource, record in [
        ("tags", tag),
        ("devices", device),
        ("connections", connection),
        ("locations", child),
        ("locations", location),
    ]:
        response = await api.delete(f"/api/{resource}/{record['id']}")
        assert response.status_code == 204, response.text
        assert response.content == b""
        assert (await api.get(f"/api/{resource}/{record['id']}")).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"protocol": "invalid"},
        {"protocol": "modbus_tcp"},
        {"protocol": "modbus_tcp", "host": "https://test.local"},
        {"protocol": "modbus_tcp", "host": "host", "port": 0},
        {"protocol": "modbus_tcp", "host": "host", "port": 65536},
        {"protocol": "modbus_tcp", "host": "host", "port": None},
        {"protocol": "modbus_tcp", "host": "host", "serial_port": "typed-port"},
        {"protocol": "modbus_rtu", "serial_port": "typed-port"},
        {
            "protocol": "modbus_rtu",
            "serial_port": " ",
            "baud_rate": 9600,
            "parity": "N",
            "stop_bits": 1,
            "data_bits": 8,
        },
        {
            "protocol": "modbus_rtu",
            "serial_port": "typed-port",
            "baud_rate": 9600,
            "parity": "X",
            "stop_bits": 1,
            "data_bits": 8,
        },
        {
            "protocol": "modbus_rtu",
            "serial_port": "typed-port",
            "baud_rate": 0,
            "parity": "N",
            "stop_bits": 1,
            "data_bits": 8,
        },
        {"protocol": "modbus_tcp", "host": "host", "timeout_ms": 0},
    ],
)
async def test_connection_validation(api: AsyncClient, payload: dict[str, Any]) -> None:
    response = await api.post("/api/connections", json={"name": "Test", **payload})
    assert response.status_code == 422, response.text


async def test_rtu_and_protocol_switch_patch(api: AsyncClient) -> None:
    connection = await create(
        api,
        "connections",
        name="Serial",
        protocol="modbus_rtu",
        serial_port="operator-entered-port",
        baud_rate=19200,
        parity="E",
        stop_bits=1,
        data_bits=8,
    )
    path = f"/api/connections/{connection['id']}"
    assert (await api.patch(path, json={"parity": "O"})).status_code == 200
    assert (await api.patch(path, json={"parity": None})).status_code == 422
    assert (await api.patch(path, json={"protocol": "modbus_tcp"})).status_code == 422
    response = await api.patch(
        path,
        json={
            "protocol": "modbus_tcp",
            "host": "::1",
            "port": 502,
            "serial_port": None,
            "baud_rate": None,
            "parity": None,
            "stop_bits": None,
            "data_bits": None,
        },
    )
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "change",
    [
        {"key": "UPPER"},
        {"key": "with space"},
        {"key": "with.dot"},
        {"key": "1first"},
        {"key": "a" * 65},
        {"address": -1},
        {"address": 65536},
        {"address": 65535, "data_type": "uint32"},
        {"address": 65533, "data_type": "float64"},
        {"poll_interval_ms": 0},
        {"min_value": 10, "max_value": 1},
        {"data_type": "bool"},
        {"register_type": "coil", "data_type": "int16"},
        {"register_type": "discrete_input", "data_type": "bool", "writable": True},
        {"register_type": "input_register", "writable": True},
        {"byte_order": "middle"},
        {"word_order": "middle"},
        {"name": " "},
        {"address": True},
    ],
)
async def test_tag_validation_on_create_and_patch(
    api: AsyncClient, change: dict[str, Any]
) -> None:
    tag = await setup_tag(api)
    values = {
        key: value
        for key, value in tag.items()
        if key not in ("id", "created_at", "updated_at")
    }
    values.update(change)
    assert (await api.post("/api/tags", json=values)).status_code == 422
    response = await api.patch(f"/api/tags/{tag['id']}", json=change)
    assert response.status_code == 422, response.text
    assert (await api.get(f"/api/tags/{tag['id']}")).json()["address"] == 0


@pytest.mark.parametrize(
    "register_type,data_type,writable",
    [
        ("coil", "bool", True),
        ("discrete_input", "bool", False),
        *[
            ("holding_register", data_type, True)
            for data_type in (
                "uint16",
                "int16",
                "uint32",
                "int32",
                "float32",
                "uint64",
                "int64",
                "float64",
            )
        ],
        ("input_register", "uint16", False),
    ],
)
async def test_supported_encodings(
    api: AsyncClient, register_type: str, data_type: str, writable: bool
) -> None:
    tag = await setup_tag(
        api, register_type=register_type, data_type=data_type, writable=writable
    )
    assert tag["data_type"] == data_type


async def test_unique_keys_and_device_addresses(api: AsyncClient) -> None:
    tag = await setup_tag(api)
    values = {
        key: value
        for key, value in tag.items()
        if key not in ("id", "created_at", "updated_at")
    }
    assert (await api.post("/api/tags", json=values)).status_code == 409
    other = await create(api, "tags", **{**values, "key": "other"})
    assert (
        await api.patch(f"/api/tags/{other['id']}", json={"key": tag["key"]})
    ).status_code == 409
    device = (await api.get(f"/api/devices/{tag['device_id']}")).json()
    assert (
        await api.post(
            "/api/devices",
            json={
                "name": "Duplicate",
                "connection_id": device["connection_id"],
                "slave_id": 1,
            },
        )
    ).status_code == 409
    # A failed transaction must not poison later requests.
    assert (
        await api.patch(f"/api/tags/{other['id']}", json={"name": "Still editable"})
    ).status_code == 200


async def test_location_hierarchy(api: AsyncClient) -> None:
    root = await create(api, "locations", name="Root")
    child = await create(api, "locations", name="Child", parent_id=root["id"])
    leaf = await create(api, "locations", name="Leaf", parent_id=child["id"])
    for parent in (root["id"], child["id"], leaf["id"]):
        assert (
            await api.patch(f"/api/locations/{root['id']}", json={"parent_id": parent})
        ).status_code == 422
    assert (
        await api.post("/api/locations", json={"name": "Orphan", "parent_id": 999})
    ).status_code == 422
    assert (await api.get(f"/api/locations?parent_id={root['id']}")).json()[0][
        "id"
    ] == child["id"]
    assert len((await api.get("/api/locations?roots_only=true")).json()) == 1
    assert (
        await api.patch(f"/api/locations/{leaf['id']}", json={"parent_id": None})
    ).status_code == 200
    assert len((await api.get("/api/locations?roots_only=true")).json()) == 2


async def test_foreign_key_validation(api: AsyncClient) -> None:
    assert (
        await api.post(
            "/api/devices", json={"name": "Orphan", "connection_id": 999, "slave_id": 1}
        )
    ).status_code == 422
    tag = await setup_tag(api)
    assert (
        await api.patch(f"/api/devices/{tag['device_id']}", json={"location_id": 999})
    ).status_code == 422
    assert (
        await api.patch(f"/api/devices/{tag['device_id']}", json={"connection_id": 999})
    ).status_code == 422
    assert (
        await api.patch(f"/api/tags/{tag['id']}", json={"device_id": 999})
    ).status_code == 422


@pytest.mark.parametrize("slave_id", [0, 248, -1, 1.5, True])
async def test_slave_id_scope(api: AsyncClient, slave_id: Any) -> None:
    device = await setup_device(api)
    assert (
        await api.patch(f"/api/devices/{device['id']}", json={"slave_id": slave_id})
    ).status_code == 422


async def test_filters_and_pagination(api: AsyncClient) -> None:
    tag = await setup_tag(api, name="Temperature", key="boiler_temp")
    device = tag["device_id"]
    await create(
        api,
        "tags",
        name="Switch",
        key="switch",
        device_id=device,
        register_type="coil",
        data_type="bool",
        address=5,
        enabled=False,
    )
    for query in (
        "search=TEMP",
        "register_type=holding_register",
        "enabled=true",
        "search=boiler_",
        f"device_id={device}&enabled=true",
    ):
        result = (await api.get(f"/api/tags?{query}")).json()
        assert len(result) == 1 and result[0]["id"] == tag["id"]
    assert (await api.get("/api/tags?search=%25")).json() == []
    assert (await api.get("/api/tags?device_id=999")).json() == []
    assert len((await api.get("/api/tags?enabled=false")).json()) == 1
    first = (await api.get("/api/tags?limit=1&offset=0")).json()
    second = (await api.get("/api/tags?limit=1&offset=1")).json()
    assert len(first) == len(second) == 1 and first[0]["id"] != second[0]["id"]
    assert (await api.get("/api/tags?limit=501")).status_code == 422
    assert (await api.get("/api/tags?register_type=invalid")).status_code == 422
    assert (
        len((await api.get("/api/connections?protocol=modbus_tcp&enabled=true")).json())
        == 1
    )
    assert (await api.get("/api/connections?protocol=modbus_rtu")).json() == []
    assert len((await api.get("/api/devices?connection_id=1&enabled=true")).json()) == 1
    assert (await api.get("/api/devices?location_id=999")).json() == []


@pytest.mark.parametrize("resource", ["locations", "connections", "devices", "tags"])
async def test_missing_records(api: AsyncClient, resource: str) -> None:
    assert (await api.get(f"/api/{resource}/999")).status_code == 404
    assert (await api.patch(f"/api/{resource}/999", json={})).status_code == 404
    assert (await api.delete(f"/api/{resource}/999")).status_code == 404


async def test_patch_null_and_unknown_fields(api: AsyncClient) -> None:
    tag = await setup_tag(api, min_value=0, max_value=10)
    path = f"/api/tags/{tag['id']}"
    for payload in (
        {"name": None},
        {"address": None},
        {"enabled": None},
        {"scale": None},
        {"typo": 1},
    ):
        assert (await api.patch(path, json=payload)).status_code == 422
    response = await api.patch(path, json={"min_value": None, "max_value": None})
    assert response.status_code == 200
    assert response.json()["min_value"] is None


async def test_database_constraints_without_api(
    database_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with database_sessions() as session:
        root = Location(name="Root")
        session.add(root)
        await session.commit()
        child = Location(name="Child", parent_id=root.id)
        session.add(child)
        await session.commit()
        root_id = root.id
        for statement in (
            delete(Location).where(Location.id == root_id),
            insert(Device).values(name="Orphan", connection_id=999, slave_id=1),
            insert(Connection).values(name="Bad", protocol="modbus_rtu"),
            update(Location).where(Location.id == root_id).values(parent_id=root_id),
            insert(Tag).values(
                name="Bad",
                key="bad",
                device_id=999,
                address=-1,
                register_type="input_register",
                data_type="uint16",
                writable=True,
            ),
        ):
            with pytest.raises(IntegrityError):
                await session.execute(statement)
                await session.commit()
            await session.rollback()


async def test_cors_write_preflight(api: AsyncClient) -> None:
    response = await api.options(
        "/api/tags",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN"])
async def test_nonfinite_values_return_clear_validation(
    api: AsyncClient, number: str
) -> None:
    tag = await setup_tag(api)
    response = await api.patch(
        f"/api/tags/{tag['id']}",
        content='{"scale": ' + number + "}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "scale"]


async def test_device_reassignment_returns_new_protocol(api: AsyncClient) -> None:
    device = await setup_device(api)
    serial = await create(
        api,
        "connections",
        name="Serial",
        protocol="modbus_rtu",
        serial_port="operator-port",
        baud_rate=9600,
        parity="N",
        stop_bits=1,
        data_bits=8,
    )
    response = await api.patch(
        f"/api/devices/{device['id']}", json={"connection_id": serial["id"]}
    )
    assert response.status_code == 200
    assert response.json()["connection_protocol"] == "modbus_rtu"
