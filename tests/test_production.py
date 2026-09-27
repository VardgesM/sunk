"""Production settings and safety checks without network or physical hardware."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.cloud_preflight import validate
from app.core.config import Settings
from app.main import create_app
from app.sync.remote import queue_command


@pytest.mark.parametrize("mode", ["standalone", "edge", "cloud"])
def test_app_mode_alias(monkeypatch, mode):
    monkeypatch.setenv("APP_MODE", mode)
    monkeypatch.setenv("APPLICATION_MODE", "standalone")
    assert Settings(postgres_password="test").application_mode == mode
    assert Settings(application_mode="edge", postgres_password="test").application_mode == "edge"


def test_legacy_mode(monkeypatch):
    monkeypatch.delenv("APP_MODE", raising=False)
    monkeypatch.setenv("APPLICATION_MODE", "edge")
    assert Settings(postgres_password="test").application_mode == "edge"


def cloud_settings(**overrides):
    return Settings(
        **(
            {
                "postgres_password": "test",
                "application_mode": "cloud",
                "telemetry_source": "disabled",
                "auth_cookie_secure": True,
                "allowed_hosts": ["monitor.example.com"],
                "cors_origins": ["https://monitor.example.com"],
            }
            | overrides
        )
    )


def test_cloud_preflight_https_and_http():
    validate(cloud_settings(), "monitor.example.com", "https", "https://monitor.example.com")
    validate(
        cloud_settings(auth_cookie_secure=False, cors_origins=["http://monitor.example.com"]),
        "monitor.example.com",
        "http",
        "http://monitor.example.com",
    )


@pytest.mark.parametrize(
    "override",
    [
        {"auth_cookie_secure": False},
        {"allowed_hosts": ["*"]},
        {"cors_origins": ["https://other.example.com"]},
        {"application_mode": "edge"},
        {"telemetry_source": "modbus"},
    ],
)
def test_cloud_preflight_rejects_unsafe_configuration(override):
    with pytest.raises(ValueError):
        validate(
            cloud_settings(**override),
            "monitor.example.com",
            "https",
            "https://monitor.example.com",
        )


@pytest.mark.anyio
async def test_untrusted_http_host_rejected():
    app = create_app(
        Settings(
            postgres_password="test",
            allowed_hosts=["monitor.example.com"],
            live_updates_enabled=False,
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://evil.example.com"
        ) as api,
    ):
        assert (await api.get("/api/health")).status_code == 400
        assert (
            await api.get("/api/health", headers={"Host": "monitor.example.com"})
        ).status_code == 200


@pytest.mark.anyio
async def test_cloud_physical_write_gate_even_if_edge_enabled(monkeypatch):
    edge = SimpleNamespace(runtime={"mode": "modbus", "writes_enabled": True})
    monkeypatch.setattr("app.sync.remote.cloud_mapping", AsyncMock(return_value=(edge, None)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=cloud_settings())))
    with pytest.raises(HTTPException) as result:
        await queue_command(None, request, None, SimpleNamespace(id=1), None, None)
    assert result.value.status_code == 409
    assert "disabled on Cloud" in result.value.detail
