"""Run `python -m app.bootstrap`; credentials are prompted, never passed as CLI arguments."""

import asyncio
from getpass import getpass

from sqlalchemy import func, select

from app.core.config import Settings
from app.db.session import Database
from app.models import AuditLog, User
from app.schemas.auth import UserCreate
from app.services.auth import hash_password, user_lock


async def bootstrap(username: str, password: str) -> None:
    payload = UserCreate(username=username, password=password, role="ADMIN")
    database = Database(Settings())
    try:
        async with database.sessions() as session:
            await user_lock(session)
            if await session.scalar(select(func.count()).select_from(User)):
                raise RuntimeError("Bootstrap refused: users already exist")
            user = User(
                username=payload.username,
                role="ADMIN",
                enabled=True,
                password_hash=await asyncio.to_thread(hash_password, password),
            )
            session.add(user)
            await session.flush()
            session.add(
                AuditLog(
                    user_id=user.id,
                    username=user.username,
                    action="users.bootstrap",
                    entity_type="users",
                    entity_id=user.id,
                    summary="First administrator created locally",
                )
            )
            await session.commit()
    finally:
        await database.close()


def main() -> None:
    username = input("Initial ADMIN username: ").strip()
    password = getpass("Initial ADMIN password (non-empty, up to 128 characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        asyncio.run(bootstrap(username, password))
    except (ValueError, RuntimeError):
        raise SystemExit(
            "Bootstrap refused. Use a valid username and non-empty password of at most 128 characters; users must not already exist."
        ) from None
    print("Initial ADMIN created. Sign in through the web application.")


if __name__ == "__main__":
    main()
