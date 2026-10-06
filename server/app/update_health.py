"""Local container health probe for the trusted deployment runner (no credentials in output)."""

import asyncio
import json
import urllib.request

from sqlalchemy import text

from app.core.config import Settings
from app.core.version import APP_VERSION
from app.db.session import Database


async def inspect() -> dict:
    settings = Settings()
    database = Database(settings)
    try:
        async with database.sessions() as session:
            await session.execute(text("SELECT 1"))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        # Tests the actual running HTTP process, not just a fresh DB connection.
        for endpoint in ("/api/health", "/api/health/db"):
            with urllib.request.urlopen("http://127.0.0.1:8000" + endpoint, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("API health unavailable")
        return {
            "version": APP_VERSION,
            "revision": revision,
            "mode": settings.application_mode,
            "writes_enabled": settings.modbus_writes_enabled,
        }
    finally:
        await database.close()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(inspect())))
    except Exception:
        raise SystemExit("Application health verification failed") from None
