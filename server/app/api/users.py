import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import AuditLog, User
from app.schemas.auth import AuditRead, PasswordInput, UserCreate, UserFields, UserRead
from app.services.auth import hash_password, revoke, user_lock

router = APIRouter(prefix="/api", tags=["users and audit"])
Session = Annotated[AsyncSession, Depends(get_session)]
Identifier = Annotated[int, Path(ge=1, le=2147483647)]


async def require(session: AsyncSession, identifier: int) -> User:
    user = await session.get(User, identifier, populate_existing=True)
    if user is None:
        raise HTTPException(404, "User not found")
    return user


async def commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Username already exists or user is referenced") from None


async def protect_admin(session: AsyncSession, user: User, role: str, enabled: bool) -> None:
    if user.role == "ADMIN" and user.enabled and (role != "ADMIN" or not enabled):
        count = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.enabled, User.role == "ADMIN", User.id != user.id)
        )
        if count == 0:
            raise HTTPException(409, "Cannot remove the last enabled ADMIN")


@router.get("/users", response_model=list[UserRead])
async def list_users(
    session: Session, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    return list(await session.scalars(select(User).order_by(User.id).limit(limit).offset(offset)))


@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(payload: UserCreate, session: Session):
    await user_lock(session)
    user = User(
        **payload.model_dump(exclude={"password"}),
        password_hash=await asyncio.to_thread(hash_password, payload.password.get_secret_value()),
    )
    session.add(user)
    await commit(session)
    return user


@router.patch("/users/{identifier}", response_model=UserRead)
async def edit_user(identifier: Identifier, changes: dict, session: Session):
    await user_lock(session)
    user = await require(session, identifier)
    try:
        payload = UserFields.model_validate(
            {**{key: getattr(user, key) for key in UserFields.model_fields}, **changes}
        )
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from None
    await protect_admin(session, user, payload.role, payload.enabled)
    # Capture only enumerated, non-secret changes; never request bodies.
    session.info["audit"]["summary"] = (
        f"User configuration: role {user.role} -> {payload.role}; enabled {user.enabled} -> {payload.enabled}; username {user.username} -> {payload.username}"
    )
    for key, value in payload.model_dump().items():
        setattr(user, key, value)
    await revoke(session, user.id)
    await commit(session)
    return user


@router.post("/users/{identifier}/password", status_code=204)
async def reset_password(
    identifier: Identifier, payload: PasswordInput, request: Request, session: Session
):
    if identifier == request.state.user.id:
        raise HTTPException(
            409, "Use change password with your current password for your own account"
        )
    await user_lock(session)
    user = await require(session, identifier)
    user.password_hash = await asyncio.to_thread(hash_password, payload.password.get_secret_value())
    await revoke(session, user.id)
    await commit(session)
    return Response(status_code=204)


@router.delete("/users/{identifier}", status_code=204)
async def delete_user(identifier: Identifier, request: Request, session: Session):
    await user_lock(session)
    user = await require(session, identifier)
    await protect_admin(session, user, "VIEWER", False)
    await revoke(session, user.id)
    if request.state.user.id == identifier:
        session.info["audit"]["user_id"] = None
    await session.delete(user)
    await commit(session)
    return Response(status_code=204)


@router.get("/audit", response_model=list[AuditRead])
async def audit(
    session: Session,
    user_id: int | None = Query(None, ge=1),
    action: str | None = Query(None, max_length=100),
    from_time: datetime | None = Query(None, alias="from"),
    to_time: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    if (
        any(value is not None and value.tzinfo is None for value in (from_time, to_time))
        or from_time
        and to_time
        and from_time > to_time
    ):
        raise HTTPException(422, "Use a valid range with UTC offsets")
    statement = select(AuditLog)
    if user_id is not None:
        statement = statement.where(AuditLog.user_id == user_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    if from_time:
        statement = statement.where(AuditLog.timestamp >= from_time)
    if to_time:
        statement = statement.where(AuditLog.timestamp <= to_time)
    return list(
        await session.scalars(statement.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    )
