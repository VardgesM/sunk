from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.api.live import live
from app.models import AlarmEvent, AuditLog, AuthSession, User
from app.services.auth import digest, verify_password
from tests.auth_helpers import TEST_PASSWORD
from tests.test_configuration import setup_tag

pytestmark = pytest.mark.anyio


async def account(api, role="VIEWER", username="reader"):
    response = await api.post(
        "/api/users", json={"username": username, "role": role, "password": "another-test-password"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def sign_in(api, username="test_admin", password=TEST_PASSWORD):
    response = await api.post("/api/auth/login", json={"username": username, "password": password})
    if response.status_code == 200:
        api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
    return response


async def test_login_cookie_me_logout_and_hashed_storage(api, database_sessions):
    assert (await api.get("/api/auth/me")).json()["role"] == "ADMIN"
    login = await sign_in(api)
    cookies = login.headers.get_list("set-cookie")
    assert any("HttpOnly" in c and "SameSite=strict" in c for c in cookies)
    token = api.cookies["mm_session"]
    async with database_sessions() as session:
        stored = await session.get(AuthSession, digest(token))
        assert stored and stored.token_hash != token
        user = await session.get(User, stored.user_id)
        assert user.password_hash.startswith("$argon2id$") and verify_password(
            user.password_hash, TEST_PASSWORD
        )
    assert "password" not in login.text
    assert (await api.post("/api/auth/logout")).status_code == 204
    assert (await api.get("/api/auth/me")).status_code == 401
    assert (await api.get("/api/tags")).status_code == 401


async def test_invalid_disabled_login_generic_and_rate_limit(api):
    row = await account(api)
    await api.patch(f"/api/users/{row['id']}", json={"enabled": False})
    invalid = await sign_in(api, password="incorrect")
    disabled = await sign_in(api, "reader", "another-test-password")
    unknown = await sign_in(api, "missing", "another-test-password")
    assert invalid.status_code == disabled.status_code == unknown.status_code == 401
    assert invalid.json() == disabled.json() == unknown.json()
    for _ in range(10):
        response = await sign_in(api, "missing", "incorrect")
    assert response.status_code == 429 and "Retry-After" in response.headers


async def test_session_expiration_csrf_and_origin(api, database_sessions):
    assert (
        await api.post(
            "/api/dashboards", json={"name": "X", "slug": "x"}, headers={"X-CSRF-Token": "wrong"}
        )
    ).status_code == 403
    assert (
        await api.post("/api/auth/logout", headers={"Origin": "https://evil.invalid"})
    ).status_code == 403
    assert (
        await api.post(
            "/api/auth/login",
            json={"username": "test_admin", "password": TEST_PASSWORD},
            headers={"Origin": "https://evil.invalid"},
        )
    ).status_code == 403
    async with database_sessions() as session:
        await session.execute(
            update(AuthSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (await api.get("/api/tags")).status_code == 401


@pytest.mark.parametrize("role", ["VIEWER", "OPERATOR"])
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/tags", {}),
        ("patch", "/api/tags/1", {}),
        ("delete", "/api/connections/1", None),
        ("post", "/api/automation/rules", {}),
        ("patch", "/api/automation/rules/1", {}),
        ("post", "/api/alarms/rules", {}),
        ("patch", "/api/alarms/rules/1", {}),
        ("post", "/api/dashboards", {}),
        ("patch", "/api/dashboards/1/layout", {}),
        ("post", "/api/connections/1/test", None),
        ("post", "/api/connections/1/redetect", None),
        ("get", "/api/users", None),
        ("get", "/api/audit", None),
        ("get", "/api/notifications/telegram/destination", None),
        ("get", "/api/system/serial-ports", None),
    ],
)
async def test_roles_cannot_mutate_or_read_sensitive(api, role, method, path, body):
    await account(api, role)
    await sign_in(api, "reader", "another-test-password")
    assert (await api.request(method, path, json=body)).status_code == 403


@pytest.mark.parametrize("role", ["VIEWER", "OPERATOR"])
async def test_read_access_and_manual_command_permission(api, role):
    await account(api, role)
    await sign_in(api, "reader", "another-test-password")
    for path in (
        "/api/tags",
        "/api/devices",
        "/api/connections",
        "/api/dashboards",
        "/api/commands",
        "/api/automation/rules",
        "/api/alarms/rules",
        "/api/alarms/events",
        "/api/tags/values",
    ):
        assert (await api.get(path)).status_code == 200, path
    expected = 403 if role == "VIEWER" else 404
    assert (await api.post("/api/tags/999/commands", json={"value": True})).status_code == expected
    assert (await api.post("/api/alarms/events/999/acknowledge")).status_code == expected
    assert (await api.post("/api/commands/999/cancel")).status_code == expected


async def test_user_management_passwords_and_last_admin(api, database_sessions):
    admin = (await api.get("/api/auth/me")).json()
    for patch in ({"enabled": False}, {"role": "VIEWER"}):
        assert (await api.patch(f"/api/users/{admin['id']}", json=patch)).status_code == 409
    assert (await api.delete(f"/api/users/{admin['id']}")).status_code == 409
    row = await account(api)
    assert (
        await api.patch(
            f"/api/users/{row['id']}", json={"username": "READER_TWO", "role": "OPERATOR"}
        )
    ).json()["username"] == "reader_two"
    assert (
        await api.post(f"/api/users/{row['id']}/password", json={"password": "reset-test-password"})
    ).status_code == 204
    assert (
        await api.post(
            "/api/auth/password",
            json={"current_password": "wrong", "password": "new-test-password"},
        )
    ).status_code == 400
    assert (
        await api.post(
            "/api/auth/password",
            json={"current_password": TEST_PASSWORD, "password": "new-test-password"},
        )
    ).status_code == 204
    assert (await api.get("/api/auth/me")).status_code == 401
    assert (await sign_in(api, password="new-test-password")).status_code == 200
    assert (await api.delete(f"/api/users/{row['id']}")).status_code == 204
    async with database_sessions() as session:
        logs = list(await session.scalars(select(AuditLog)))
        serialized = " ".join(str((r.action, r.summary)) for r in logs)
        for secret in (
            TEST_PASSWORD,
            "reset-test-password",
            "new-test-password",
            api.cookies["mm_session"],
        ):
            assert secret not in serialized
        assert {
            "users.post",
            "users.patch",
            "users.password_reset",
            "users.delete",
            "auth.password",
        } <= {r.action for r in logs}
    assert all("password_hash" not in r for r in (await api.get("/api/users")).json())


async def test_disable_and_role_change_revoke_sessions(api, database_sessions):
    row = await account(api, "OPERATOR")
    await sign_in(api, "reader", "another-test-password")
    old = api.cookies["mm_session"]
    await sign_in(api)
    assert (await api.patch(f"/api/users/{row['id']}", json={"role": "VIEWER"})).status_code == 200
    async with database_sessions() as session:
        assert await session.get(AuthSession, digest(old)) is None


async def test_alarm_attribution_and_audit_persist_after_user_delete(api, database_sessions):
    tag = await setup_tag(api)
    rule = (
        await api.post(
            "/api/alarms/rules",
            json={
                "name": "Threshold",
                "tag_id": tag["id"],
                "operator": ">",
                "value": "10",
                "severity": "WARNING",
            },
        )
    ).json()
    async with database_sessions() as session:
        event = AlarmEvent(
            rule_id=rule["id"],
            tag_id=tag["id"],
            name="Threshold",
            tag_name=tag["name"],
            condition="> 10",
            severity="WARNING",
            state="ACTIVE",
            activated_at=datetime.now(UTC),
            value_numeric=11,
            revision=1,
        )
        session.add(event)
        await session.commit()
        identifier = event.id
    operator = await account(api, "OPERATOR")
    await sign_in(api, "reader", "another-test-password")
    ack = await api.post(f"/api/alarms/events/{identifier}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["acknowledged_by"] == operator["id"]
    await sign_in(api)
    assert (await api.delete(f"/api/users/{operator['id']}")).status_code == 204
    async with database_sessions() as session:
        event = await session.get(AlarmEvent, identifier)
        assert event.acknowledged_by is None and event.acknowledged_by_username == "reader"
    logs = (await api.get("/api/audit?action=alarms.acknowledge")).json()
    assert logs[0]["user_id"] is None and logs[0]["username"] == "reader"
    assert (await api.get("/api/audit?from=2026-01-01")).status_code == 422
    assert (await api.delete("/api/audit/1")).status_code == 404


async def test_websocket_rejects_unauthenticated(database_sessions):
    socket = SimpleNamespace(
        headers={},
        cookies={},
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(cors_origins=[]),
                database=SimpleNamespace(sessions=database_sessions),
            )
        ),
        close=AsyncMock(),
        accept=AsyncMock(),
    )
    await live(socket)
    socket.accept.assert_not_awaited()
    socket.close.assert_awaited_with(code=4401, reason="Authentication required")


async def test_manual_command_attribution_audit_and_worker_without_session(api, database_sessions):
    from app.models import Command
    from tests.test_commands import prepare, processor

    tag = await prepare(api, database_sessions, register_type="coil", data_type="bool")
    operator = await account(api, "OPERATOR")
    await sign_in(api, "reader", "another-test-password")
    response = await api.post(f"/api/tags/{tag['id']}/commands", json={"value": True})
    assert response.status_code == 202, response.text
    command = response.json()
    assert (
        command["requested_by"] == operator["id"] and command["requested_by_username"] == "reader"
    )
    await api.post("/api/auth/logout")
    proc = processor(database_sessions)
    await proc.process(command["id"])
    async with database_sessions() as session:
        stored = await session.get(Command, command["id"])
        assert stored.status == "SUCCESS"
        log = await session.scalar(select(AuditLog).where(AuditLog.action == "commands.request"))
        assert log.user_id == operator["id"] and log.entity_id == command["id"]
    await sign_in(api)
    assert (await api.get("/api/audit?action=tags.post")).json()[0]["entity_id"] == tag["id"]


def test_all_http_api_routes_have_authorization():
    from fastapi.routing import APIRoute

    from app.core.config import Settings
    from app.main import create_app
    from app.services.auth import authorize

    app = create_app(Settings(postgres_password="test"))
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path.startswith("/api/")
            and route.path != "/api/auth/login"
        ):
            assert any(
                dependency.call is authorize for dependency in route.dependant.dependencies
            ), route.path


async def test_bootstrap_only_empty_database(monkeypatch, database_sessions):
    from app import bootstrap as module

    database = SimpleNamespace(sessions=database_sessions, close=AsyncMock())
    monkeypatch.setattr(module, "Database", lambda _settings: database)
    await module.bootstrap("first_admin", "bootstrap-test-password")
    async with database_sessions() as session:
        user = await session.scalar(select(User))
        assert user.role == "ADMIN" and user.enabled
        assert verify_password(user.password_hash, "bootstrap-test-password")
        original_hash = user.password_hash
    with pytest.raises(RuntimeError, match="users already exist"):
        await module.bootstrap("replacement", "replacement-password")
    async with database_sessions() as session:
        users = list(await session.scalars(select(User)))
        assert len(users) == 1 and users[0].password_hash == original_hash
    assert database.close.await_count == 2
