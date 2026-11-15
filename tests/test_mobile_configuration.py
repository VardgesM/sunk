"""Remote configuration uses normal validation and commits one durable receipt."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.models import AuthSession, Location, RemoteInbox, User
from app.services.auth import digest
from app.sync.protocol import RemoteAction
from app.sync.remote import accept_remote
from tests.auth_helpers import TEST_PASSWORD

pytestmark = pytest.mark.anyio


async def test_persistent_mobile_login_logout_csrf_and_revocation(
    api, database_sessions
):
    response = await api.post(
        "/api/auth/mobile/login",
        json={"username": "test_admin", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert any(
        "9999" in h and "HttpOnly" in h for h in response.headers.get_list("set-cookie")
    )
    token = api.cookies["mm_session"]
    api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
    async with database_sessions() as session:
        row = await session.get(AuthSession, digest(token))
        assert row.expires_at is None
        user_id = row.user_id
        row.created_at = datetime.now(UTC) - timedelta(days=3650)
        await session.commit()
    assert (await api.get("/api/auth/me")).status_code == 200
    assert (
        await api.post("/api/auth/logout", headers={"X-CSRF-Token": "bad"})
    ).status_code == 403
    async with database_sessions() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(enabled=False)
        )
        await session.commit()
    assert (await api.get("/api/auth/me")).status_code == 401
    async with database_sessions() as session:
        await session.execute(
            update(User).where(User.id == user_id).values(enabled=True)
        )
        await session.commit()
    assert (await api.post("/api/auth/logout")).status_code == 204
    assert (await api.get("/api/auth/me")).status_code == 401


async def test_remember_upgrades_valid_session_but_not_expired(api, database_sessions):
    token = api.cookies["mm_session"]
    assert (
        await api.post("/api/auth/mobile/remember", headers={"X-CSRF-Token": "bad"})
    ).status_code == 403
    response = await api.post("/api/auth/mobile/remember")
    assert response.status_code == 204, response.text
    async with database_sessions() as session:
        assert (await session.get(AuthSession, digest(token))).expires_at is None
    assert any("9999" in value for value in response.headers.get_list("set-cookie"))
    assert (await api.post("/api/auth/logout")).status_code == 204
    assert (await api.post("/api/auth/mobile/remember")).status_code == 401


def action(
    edge_id,
    *,
    path="locations",
    method="POST",
    values=None,
    versions=None,
    expired=False,
):
    return RemoteAction(
        id=uuid4(),
        edge_id=edge_id,
        kind="configuration",
        target_id=int(path.split("/")[-1]) if method != "POST" else 0,
        user_id=2,
        username="remote_admin",
        expires_at=datetime.now(UTC) + timedelta(seconds=-1 if expired else 300),
        payload={
            "fingerprint": "a" * 64,
            "path": path,
            "method": method,
            "values": values if values is not None else {"name": "Remote location"},
            "versions": versions or [],
        },
    )


async def test_edge_create_duplicate_and_transaction_rollback(database_sessions):
    identity = str(uuid4())
    settings = Settings(postgres_password="test", application_mode="edge")
    request = action(identity)
    async with database_sessions() as session, session.begin():
        first = await accept_remote(session, settings, request, identity)
        assert first.status == "SUCCESS", first.error
        assert first.result["id"] > 0
    async with database_sessions() as session, session.begin():
        again = await accept_remote(session, settings, request, identity)
        assert again.result == first.result
        assert await session.scalar(select(func.count()).select_from(Location)) == 1
    # A cancelled outer transaction must not leave either a mutation or receipt.
    next_request = action(identity, values={"name": "Rollback me"})
    async with database_sessions() as session:
        # SQLite needs a real transaction before SAVEPOINT, unlike PostgreSQL.
        await session.execute(update(Location).values(sort_order=Location.sort_order))
        assert (
            await accept_remote(session, settings, next_request, identity)
        ).status == "SUCCESS"
        await session.rollback()
    async with database_sessions() as session:
        assert await session.get(RemoteInbox, str(next_request.id)) is None
        assert await session.scalar(select(func.count()).select_from(Location)) == 1


@pytest.mark.parametrize("case", ["expired", "disabled", "invalid", "forbidden_path"])
async def test_rejected_configuration_has_no_side_effects(database_sessions, case):
    identity = str(uuid4())
    settings = Settings(
        postgres_password="test",
        application_mode="edge",
        remote_configuration_enabled=case != "disabled",
    )
    request = action(
        identity,
        expired=case == "expired",
        values={} if case == "invalid" else None,
        path="system/updates/install" if case == "forbidden_path" else "locations",
    )
    async with database_sessions() as session, session.begin():
        row = await accept_remote(session, settings, request, identity)
        assert row.status == ("EXPIRED" if case == "expired" else "FAILED")
        assert row.error
        assert await session.scalar(select(func.count()).select_from(Location)) == 0


async def test_stale_configuration_is_not_overwritten(api, database_sessions):
    location = (await api.post("/api/locations", json={"name": "Original"})).json()
    identity = str(uuid4())
    request = action(
        identity,
        path=f"locations/{location['id']}",
        method="PATCH",
        values={"name": "Remote"},
        versions=[
            {
                "entity": "locations",
                "id": location["id"],
                "updated_at": location["updated_at"],
            }
        ],
    )
    assert (
        await api.patch(f"/api/locations/{location['id']}", json={"name": "New local"})
    ).status_code == 200
    async with database_sessions() as session, session.begin():
        result = await accept_remote(
            session,
            Settings(postgres_password="test", application_mode="edge"),
            request,
            identity,
        )
        assert result.status == "FAILED" and "changed" in result.error
        assert (await session.get(Location, location["id"])).name == "New local"
