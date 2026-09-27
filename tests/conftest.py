from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.db.session import get_session
from app.main import create_app


@pytest.fixture(autouse=True)
def disable_background_database_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVE_UPDATES_ENABLED", "false")
    monkeypatch.setenv("TELEMETRY_SOURCE", "")
    monkeypatch.setenv("SIMULATOR_ENABLED", "false")
    monkeypatch.setenv("MODBUS_WRITES_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def database_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    # Isolated relational tests, not a replacement for PostgreSQL migration/integration tests.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
async def api(
    database_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(postgres_password="test-only"))

    async def session() -> AsyncIterator[AsyncSession]:
        async with database_sessions() as database_session:
            yield database_session

    app.dependency_overrides[get_session] = session
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            from tests.auth_helpers import login_test_admin

            await login_test_admin(client, database_sessions)
            yield client
