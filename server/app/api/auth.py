import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import AuditLog, LoginLimit, User
from app.schemas.auth import Login, Me, PasswordChange
from app.services.auth import (
    COOKIE,
    CSRF_COOKIE,
    DUMMY_HASH,
    HASHER,
    authorize,
    digest,
    hash_password,
    me,
    origin_check,
    revoke,
    start_session,
    user_lock,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])
Session = Annotated[AsyncSession, Depends(get_session)]


def clear_cookies(response: Response, secure: bool) -> None:
    for key in (COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            key, path="/", secure=secure, httponly=key == COOKIE, samesite="strict"
        )


@router.post("/login", response_model=Me)
async def login(payload: Login, request: Request, response: Response, session: Session) -> Me:
    origin_check(request)
    config = request.app.state.settings
    now = datetime.now(UTC)
    await user_lock(session)
    await session.execute(
        delete(LoginLimit).where(
            LoginLimit.started_at < now - timedelta(seconds=config.auth_login_window_seconds)
        )
    )
    # Do not trust forwarding headers or retain raw client addresses/attempted usernames.
    keys = [
        digest("ip:" + (request.client.host if request.client else "unknown")),
        digest("user:" + payload.username.lower()),
    ]
    limits = []
    for key in keys:
        limit = await session.get(LoginLimit, key)
        if limit is None:
            limit = LoginLimit(bucket=key, started_at=now, failures=0)
            session.add(limit)
        limits.append(limit)
        if limit.failures >= config.auth_login_attempts:
            await session.commit()
            raise HTTPException(
                429,
                "Too many login attempts; try again later",
                headers={"Retry-After": str(config.auth_login_window_seconds)},
            )
    user = await session.scalar(select(User).where(User.username == payload.username.lower()))
    valid = await asyncio.to_thread(
        verify_password,
        user.password_hash if user else DUMMY_HASH,
        payload.password.get_secret_value(),
    )
    if user is None or not valid or not user.enabled:
        for limit in limits:
            limit.failures += 1
        session.add(
            AuditLog(
                action="auth.login_failure",
                entity_type="auth",
                summary="Invalid login",
                user_id=None,
            )
        )
        await session.commit()
        raise HTTPException(401, "Invalid username or password")
    # Successful login resets account bucket, not the shared IP failure budget.
    limits[1].failures = 0
    if HASHER.check_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(
            hash_password, payload.password.get_secret_value()
        )
    user.last_login_at = now
    token, csrf = await start_session(session, user, config.auth_session_hours)
    session.add(
        AuditLog(
            user_id=user.id,
            username=user.username,
            action="auth.login_success",
            entity_type="auth",
            entity_id=user.id,
            summary="Login successful",
        )
    )
    await session.commit()
    for key, value in ((COOKIE, token), (CSRF_COOKIE, csrf)):
        response.set_cookie(
            key,
            value,
            max_age=config.auth_session_hours * 3600,
            path="/",
            secure=config.auth_cookie_secure,
            httponly=key == COOKIE,
            samesite="strict",
        )
    response.headers["Cache-Control"] = "no-store"
    return me(user)


@router.get("/me", response_model=Me, dependencies=[Depends(authorize)])
async def current_user(request: Request, response: Response) -> Me:
    response.headers["Cache-Control"] = "no-store"
    return me(request.state.user)


@router.post("/logout", status_code=204, dependencies=[Depends(authorize)])
async def logout(request: Request, response: Response, session: Session) -> None:
    await session.delete(request.state.auth_session)
    await session.commit()
    clear_cookies(response, request.app.state.settings.auth_cookie_secure)


@router.post("/password", status_code=204, dependencies=[Depends(authorize)])
async def change_password(
    payload: PasswordChange, request: Request, response: Response, session: Session
) -> None:
    await user_lock(session)
    user = await session.get(User, request.state.user.id, populate_existing=True)
    if not await asyncio.to_thread(
        verify_password, user.password_hash, payload.current_password.get_secret_value()
    ):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = await asyncio.to_thread(hash_password, payload.password.get_secret_value())
    await revoke(session, user.id)
    await session.commit()
    clear_cookies(response, request.app.state.settings.auth_cookie_secure)
