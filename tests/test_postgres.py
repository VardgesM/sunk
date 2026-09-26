"""Opt-in integration test, isolated in a newly created PostgreSQL schema.

Set TEST_DATABASE_URL to a postgresql+asyncpg URL with CREATE SCHEMA permission.
Only the randomly named schema created by this test is dropped, never public data.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection as SyncConnection
from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app
from app.models import Command, Tag, TagHistory
from app.services.current_values import Reading, get_current, upsert_current

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set; PostgreSQL unavailable",
    ),
]


async def test_postgres_migrations_crud_constraints_and_hierarchy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ["TEST_DATABASE_URL"]
    assert url.startswith("postgresql+asyncpg://"), "Use a postgresql+asyncpg URL"
    schema = f"phase2_test_{uuid4().hex}"
    admin = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-settings-placeholder")
    get_settings.cache_clear()
    async with admin.begin() as connection:
        await connection.execute(CreateSchema(schema))

    def migrate(connection: SyncConnection, target: str = "head") -> None:
        config = Config("server/alembic.ini")
        config.attributes["connection"] = connection
        if target == "base":
            command.downgrade(config, "base")
        else:
            command.upgrade(config, target)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
            differences = await connection.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(sync, opts={"compare_type": True}),
                    Base.metadata,
                )
            )
            assert differences == [], differences
        app = create_app(Settings(postgres_password="test-only"))

        async def session() -> AsyncIterator[AsyncSession]:
            async with sessions() as value:
                yield value

        app.dependency_overrides[get_session] = session
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as api,
        ):
            assert (await api.get("/api/health/db")).status_code == 200
            location = (await api.post("/api/locations", json={"name": "Integration root"})).json()
            other = (await api.post("/api/locations", json={"name": "Integration other"})).json()
            # Competing updates must not be able to create a cycle.
            responses = await asyncio.gather(
                api.patch(f"/api/locations/{location['id']}", json={"parent_id": other["id"]}),
                api.patch(f"/api/locations/{other['id']}", json={"parent_id": location["id"]}),
            )
            assert sorted(response.status_code for response in responses) == [200, 422]
            connection = (
                await api.post(
                    "/api/connections",
                    json={
                        "name": "Integration transport",
                        "protocol": "modbus_tcp",
                        "host": "test.local",
                    },
                )
            ).json()
            device = (
                await api.post(
                    "/api/devices",
                    json={
                        "name": "Integration device",
                        "connection_id": connection["id"],
                        "location_id": location["id"],
                        "slave_id": 1,
                    },
                )
            ).json()
            values = {
                "name": "Integration tag",
                "key": "integration_tag",
                "device_id": device["id"],
                "register_type": "holding_register",
                "address": 0,
                "data_type": "uint16",
            }
            response = await api.post("/api/tags", json=values)
            assert response.status_code == 201, response.text
            tag = response.json()
            assert (await api.post("/api/tags", json=values)).status_code == 409
            assert (
                await api.patch(f"/api/tags/{tag['id']}", json={"scale": 0.1})
            ).status_code == 200
            assert (await api.get("/api/tags?search=integration&enabled=true")).json()[0][
                "scale"
            ] == 0.1
            for resource, identifier in (
                ("devices", device["id"]),
                ("connections", connection["id"]),
                ("locations", location["id"]),
            ):
                assert (await api.delete(f"/api/{resource}/{identifier}")).status_code == 409
            channel = f"test_current_{uuid4().hex}"
            monkeypatch.setattr("app.services.current_values.CHANNEL", channel)
            notifications: asyncio.Queue[str] = asyncio.Queue()
            listener = await asyncpg.connect(
                url.replace("postgresql+asyncpg://", "postgresql://", 1)
            )
            await listener.add_listener(
                channel,
                lambda _connection, _pid, _channel, payload: notifications.put_nowait(payload),
            )
            try:
                async with sessions() as database, database.begin():
                    await upsert_current(
                        database, tag["id"], reading=Reading(Decimal(2**64 - 1), datetime.now(UTC))
                    )
                    await asyncio.sleep(0.05)
                    assert notifications.empty(), "NOTIFY must not precede COMMIT"
                assert await asyncio.wait_for(notifications.get(), 2) == str(tag["id"])
                async with sessions() as database:
                    current = await get_current(database, tag["id"])
                    assert current.value_numeric == Decimal(2**64 - 1)
                    await upsert_current(
                        database, tag["id"], quality="COMM_ERROR", error="Rolled back"
                    )
                    await database.rollback()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(notifications.get(), 0.1)
                async with sessions() as database:
                    assert (await get_current(database, tag["id"])).quality == "GOOD"
            finally:
                await listener.close()
            # History policies, SQL aggregation, rollback isolation and retention on PostgreSQL.
            assert (
                await api.patch(
                    f"/api/tags/{tag['id']}",
                    json={
                        "history_enabled": True,
                        "history_mode": "on_change",
                        "history_change_threshold": 0.2,
                    },
                )
            ).status_code == 200
            history_start = datetime.now(UTC)
            for index, value in enumerate(("22.5", "22.55", "22.61", "22.72", "23.0")):
                now = history_start + timedelta(seconds=index)
                async with sessions() as database, database.begin():
                    await upsert_current(
                        database, tag["id"], now=now, reading=Reading(Decimal(value), now)
                    )
            parameters = {
                "from": history_start.isoformat(),
                "to": (history_start + timedelta(seconds=10)).isoformat(),
            }
            response = await api.get(f"/api/tags/{tag['id']}/history", params=parameters)
            assert response.status_code == 200, response.text
            assert [p["value_numeric"] for p in response.json()["points"]] == [22.5, 22.72, 23]
            response = await api.get(
                f"/api/tags/{tag['id']}/history", params={**parameters, "max_points": 1}
            )
            assert response.status_code == 200, response.text
            point = response.json()["points"][0]
            assert (
                response.json()["downsampled"]
                and point["minimum"] == 22.5
                and point["maximum"] == 23
            )
            assert point["sample_count"] == 3
            assert (await api.delete(f"/api/tags/{tag['id']}")).status_code == 409
            async with sessions() as database:
                for values_to_insert in (
                    {
                        "quality": "GOOD",
                        "value_numeric": Decimal("Infinity"),
                        "source_timestamp": history_start,
                    },
                    {"quality": "COMM_ERROR", "value_numeric": 1},
                    {
                        "quality": "GOOD",
                        "value_numeric": 1,
                        "value_boolean": True,
                        "source_timestamp": history_start,
                    },
                    {"quality": "BAD", "tag_id": 2147483647},
                ):
                    with pytest.raises(IntegrityError):
                        await database.execute(
                            insert(TagHistory).values(**{"tag_id": tag["id"], **values_to_insert})
                        )
                        await database.commit()
                    await database.rollback()
            async with sessions() as database, database.begin():
                await database.execute(delete(TagHistory).where(TagHistory.tag_id == tag["id"]))
            # PostgreSQL-specific constraints must also reject direct SQL bypassing schemas.
            async with sessions() as database:
                for changes in (
                    {"key": "INVALID"},
                    {"key": "finite_check", "scale": float("inf")},
                    {"key": "nan_check", "offset": float("nan")},
                ):
                    with pytest.raises(IntegrityError):
                        await database.execute(insert(Tag).values(**{**values, **changes}))
                        await database.commit()
                    await database.rollback()
            # Separate queued command fixture: actual PostgreSQL SKIP LOCKED claims and numeric precision.
            from types import SimpleNamespace

            from test_runtime import worker

            from app.worker.commands import CommandProcessor
            from app.worker.simulator import SimulatorSource

            await worker(sessions, mode="simulator")
            response = await api.post(
                "/api/tags",
                json={**values, "key": "command_exact", "data_type": "uint64", "writable": True},
            )
            assert response.status_code == 201, response.text
            write_tag = response.json()
            command_ids = []
            for _ in range(2):
                response = await api.post(
                    f"/api/tags/{write_tag['id']}/commands", json={"value": "18446744073709551615"}
                )
                assert response.status_code == 202, response.text
                command_ids.append(response.json()["id"])
            proc = CommandProcessor(
                SimpleNamespace(sessions=sessions),
                Settings(postgres_password="test", telemetry_source="simulator"),
                SimulatorSource(),
            )
            claimed = await asyncio.gather(proc.claim(), proc.claim())
            assert sorted(claimed) == command_ids
            await proc.process(claimed[0])
            result = (await api.get(f"/api/commands/{claimed[0]}")).json()
            assert result["status"] == "SUCCESS", result
            assert Decimal(result["verified_value"]) == Decimal("18446744073709551615")
            assert (await api.delete(f"/api/tags/{write_tag['id']}")).status_code == 409
            async with sessions() as database:
                with pytest.raises(IntegrityError):
                    await database.execute(
                        update(Command)
                        .where(Command.id == claimed[0])
                        .values(requested_numeric=Decimal("NaN"))
                    )
                await database.rollback()
                await database.execute(delete(Command).where(Command.tag_id == write_tag["id"]))
                await database.commit()
            assert (await api.delete(f"/api/tags/{write_tag['id']}")).status_code == 204
            for resource, identifier in (
                ("tags", tag["id"]),
                ("devices", device["id"]),
                ("connections", connection["id"]),
            ):
                assert (await api.delete(f"/api/{resource}/{identifier}")).status_code == 204
            # Auto RTU fields are relational and validated by PostgreSQL, not just Pydantic.
            from app.models import Connection as ConnectionModel

            auto = await api.post(
                "/api/connections",
                json={
                    "name": "USB test",
                    "protocol": "modbus_rtu",
                    "serial_port_mode": "auto",
                    "usb_vid": 123,
                    "usb_pid": 456,
                    "baud_rate": 9600,
                    "parity": "N",
                    "stop_bits": 1,
                    "data_bits": 8,
                },
            )
            assert auto.status_code == 201, auto.text
            async with sessions() as database:
                with pytest.raises(IntegrityError):
                    await database.execute(
                        update(ConnectionModel)
                        .where(ConnectionModel.id == auto.json()["id"])
                        .values(usb_pid=None)
                    )
                    await database.commit()
                await database.rollback()
            assert (await api.delete(f"/api/connections/{auto.json()['id']}")).status_code == 204
        # Validate reversibility and replay inside the isolated schema.
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: migrate(sync, "base"))
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))
        await admin.dispose()
        get_settings.cache_clear()
