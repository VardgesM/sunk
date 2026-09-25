import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.worker import __main__ as worker


@pytest.mark.parametrize("fail", [False, True])
def test_worker_heartbeat_and_clean_shutdown(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fail: bool,
) -> None:
    async def exercise() -> None:
        stop = asyncio.Event()
        database = AsyncMock()

        async def ping() -> None:
            stop.set()
            if fail:
                raise OSError("Database disconnected")

        database.ping.side_effect = ping
        monkeypatch.setattr(worker, "Database", lambda settings: database)
        monkeypatch.setattr(worker.CommandProcessor, "run", AsyncMock())
        await asyncio.wait_for(
            worker.run(Settings(postgres_password="test-only"), stop), timeout=1,
        )
        database.ping.assert_awaited_once()
        database.close.assert_awaited_once()

    asyncio.run(exercise())
    if fail:
        assert "Worker heartbeat failed" in caplog.text
