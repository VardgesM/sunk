"""Opaque sessions, password hashing and centralized HTTP authorization."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models import AuditLog, AuthSession, User
from app.schemas.auth import Me

COOKIE = "mm_session"
CSRF_COOKIE = "mm_csrf"
HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
PERMISSIONS = {
    "ADMIN": ["read", "command", "acknowledge", "configure", "users", "audit"],
    "OPERATOR": ["read", "command", "acknowledge"],
    "VIEWER": ["read"],
}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(value: str) -> str:
    return HASHER.hash(value)


def verify_password(encoded: str, value: str) -> bool:
    try:
        return HASHER.verify(encoded, value)
    except (VerificationError, InvalidHashError):
        return False


def me(user: User, mode: str = "standalone") -> Me:
    return Me(
        id=user.id,
        username=user.username,
        role=user.role,
        permissions=[p for p in PERMISSIONS[user.role] if mode != "cloud" or p != "configure"],
        application_mode=mode,
    )


async def user_lock(session: AsyncSession) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(927010)"))


async def authenticated(
    session: AsyncSession, token: str | None
) -> tuple[User, AuthSession] | None:
    if not token or len(token) > 200:
        return None
    result = (
        await session.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                AuthSession.token_hash == digest(token),
                AuthSession.expires_at > datetime.now(UTC),
                User.enabled,
            )
        )
    ).first()
    return tuple(result) if result else None


async def revoke(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def origin_check(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = [*request.app.state.settings.cors_origins, str(request.base_url).rstrip("/")]
    if origin and origin not in allowed:
        raise HTTPException(403, "Origin not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site request not allowed")


def required_permission(method: str, path: str) -> str:
    if (
        path.startswith(("/api/users", "/api/audit", "/api/notifications"))
        or path == "/api/system/serial-ports"
    ):
        return "configure"
    if method in ("GET", "HEAD", "OPTIONS") or path.startswith("/api/auth/"):
        return "read"
    if method == "POST" and (
        path.endswith("/commands")
        and path.startswith("/api/tags/")
        or path.startswith("/api/commands/")
        and path.endswith("/cancel")
    ):
        return "command"
    if (
        method == "POST"
        and path.startswith("/api/alarms/events/")
        and path.endswith("/acknowledge")
    ):
        return "acknowledge"
    return "configure"  # All other mutations, including newly added routes, are ADMIN-only.


async def authorize(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    if request.url.path in ("/api/health", "/api/health/db"):
        return None
    identity = await authenticated(session, request.cookies.get(COOKIE))
    if not identity:
        raise HTTPException(401, "Authentication required")
    user, login = identity
    if required_permission(request.method, request.url.path) not in PERMISSIONS[user.role]:
        raise HTTPException(403, "Permission denied")
    if request.app.state.settings.application_mode == "cloud" and request.method not in (
        "GET",
        "HEAD",
        "OPTIONS",
    ):
        path = request.url.path
        allowed = path.startswith(
            ("/api/auth/", "/api/users", "/api/sync/installations")
        ) or required_permission(request.method, path) in ("command", "acknowledge")
        if not allowed:
            raise HTTPException(
                409, "Configuration is authoritative on Edge; Cloud views are read-only"
            )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin_check(request)
        token = request.headers.get("x-csrf-token", "")
        if not token or len(token) > 200 or not hmac.compare_digest(digest(token), login.csrf_hash):
            raise HTTPException(403, "Invalid CSRF token")
        path = request.url.path.removeprefix("/api/").split("/")
        entity = path[0]
        if len(path) > 1 and path[:2] in (
            ["automation", "rules"],
            ["alarms", "rules"],
            ["alarms", "events"],
        ):
            entity = {"automation": "automation", "alarms": "alarm"}[path[0]] + "_" + path[1]
        if entity == "dashboard-widgets" or path[-1] == "widgets":
            entity = "dashboard_widgets"
        action = f"{entity}.{request.method.lower()}"
        if entity == "auth":
            action = f"auth.{path[-1]}"
        elif entity == "users" and path[-1] == "password":
            action = "users.password_reset"
        elif path[-1] == "commands":
            entity, action = "commands", "commands.request"
        elif path[-1] == "acknowledge":
            entity, action = "alarm_events", "alarms.acknowledge"
        ids = [int(p) for p in path if p.isdecimal()]
        session.info["audit"] = dict(
            user_id=user.id,
            username=user.username,
            action=action,
            entity_type=entity,
            entity_id=ids[-1]
            if ids and action != "commands.request" and path[-1] != "widgets"
            else None,
            summary=f"{request.method} {'/'.join(path)}",
        )
    request.state.user = user
    request.state.auth_session = login
    return user


@event.listens_for(Session, "after_flush")
def capture_created_entity(session: Session, _context: object) -> None:
    data = session.info.get("audit")
    if data and data["entity_id"] is None:
        for obj in session.new:
            if getattr(obj, "__tablename__", None) == data["entity_type"]:
                data["entity_id"] = obj.id
                break


@event.listens_for(Session, "before_commit")
def record_mutation(session: Session) -> None:
    """Audit and business mutations commit atomically; never serialize request bodies."""
    data = session.info.pop("audit", None)
    if data:
        new = [
            obj for obj in session.new if getattr(obj, "__tablename__", None) == data["entity_type"]
        ]
        session.flush()
        if data["entity_id"] is None and new:
            data["entity_id"] = new[0].id
        session.add(AuditLog(**data))


async def start_session(session: AsyncSession, user: User, hours: int) -> tuple[str, str]:
    now = datetime.now(UTC)
    await session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    # Bound active sessions per account: retain the newest nine, then add this login.
    rows = list(
        await session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user.id)
            .order_by(AuthSession.created_at.desc())
        )
    )
    for old in rows[9:]:
        await session.delete(old)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            user_id=user.id,
            created_at=now,
            expires_at=now + timedelta(hours=hours),
        )
    )
    return token, csrf
