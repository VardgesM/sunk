from sqlalchemy import select

from app.models import User
from app.services.auth import hash_password

TEST_PASSWORD = "test-only-admin-password"
TEST_HASH = hash_password(TEST_PASSWORD)


async def login_test_admin(api, sessions):
    async with sessions() as session:
        user = await session.scalar(select(User).where(User.username == "test_admin"))
        if user is None:
            session.add(
                User(username="test_admin", role="ADMIN", enabled=True, password_hash=TEST_HASH)
            )
            await session.commit()
    response = await api.post(
        "/api/auth/login", json={"username": "test_admin", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
