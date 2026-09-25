from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from asyncpg import InvalidPasswordError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app

pytestmark = pytest.mark.anyio
ClientFixture = tuple[AsyncClient, AsyncMock]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[ClientFixture]:
    app = create_app(Settings(postgres_password="test-only-not-a-real-password"))
    session = AsyncMock()

    async def override_session() -> AsyncIterator[AsyncMock]:
        yield session

    app.dependency_overrides[get_session] = override_session
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as test_client:
            yield test_client, session


async def test_liveness_does_not_query_database(client: ClientFixture) -> None:
    http, session = client
    response = await http.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    session.execute.assert_not_awaited()


async def test_database_ready(client: ClientFixture) -> None:
    http, session = client
    response = await http.get("/api/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    session.execute.assert_awaited_once()
    assert str(session.execute.call_args.args[0]) == "SELECT 1"


@pytest.mark.parametrize("error", [
    OperationalError("SELECT 1", {}, Exception("private database details")),
    OSError("private network details"), TimeoutError("private timeout details"),
    InvalidPasswordError("private authentication details"),
])
async def test_database_unavailable(client: ClientFixture, error: Exception) -> None:
    http, session = client
    session.execute.side_effect = error
    response = await http.get("/api/health/db")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


async def test_unexpected_error_is_sanitized(client: ClientFixture) -> None:
    http, session = client
    session.execute.side_effect = RuntimeError("private internal details")
    response = await http.get("/api/health/db")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


async def test_local_cors(client: ClientFixture) -> None:
    http, _ = client
    response = await http.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    response = await http.get("/api/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in response.headers
