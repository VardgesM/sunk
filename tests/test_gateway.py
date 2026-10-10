"""Deployment boundaries and public updater health; no Docker or live network required."""

from copy import deepcopy

import httpx
import pytest

from app.updates.artifact import permitted
from app.updates.compose import public_health, validate_topology
from app.updates.store import UpdateError


def topology():
    return {
        "services": {
            "api": {"networks": {"database": {}, "web": {}}},
            "frontend": {"networks": {"web": {}}},
            "postgres": {"networks": {"database": {}}},
            "migrate": {"networks": {"database": {}}},
        },
        "networks": {"web": {"external": True}, "database": {"internal": True}},
    }


def test_external_gateway_topology():
    validate_topology(topology())


@pytest.mark.parametrize("service", ["frontend", "api", "postgres", "migrate"])
def test_application_cannot_publish_ports(service):
    config = topology()
    config["services"][service]["ports"] = [{"published": "80"}]
    with pytest.raises(UpdateError, match="publish"):
        validate_topology(config)


@pytest.mark.parametrize(
    "change", ["gateway", "private_web", "db_web", "public_db", "certificates", "socket"]
)
def test_rejects_unisolated_or_gateway_owned_topology(change):
    config = deepcopy(topology())
    if change == "gateway":
        config["services"]["caddy"] = {}
    elif change == "private_web":
        config["networks"]["web"]["external"] = False
    elif change == "db_web":
        config["services"]["postgres"]["networks"]["web"] = {}
    elif change == "public_db":
        config["networks"]["database"]["internal"] = False
    else:
        config["services"]["frontend"]["volumes"] = [
            {"target": "/data" if change == "certificates" else "/var/run/docker.sock"}
        ]
    with pytest.raises(UpdateError):
        validate_topology(config)


def test_release_excludes_independent_gateway():
    assert permitted("frontend/nginx.conf")
    assert not permitted("deploy/gateway/Caddyfile")
    assert not permitted("deploy/gateway/docker-compose.yml")
    assert not permitted("deploy/cloud/Caddyfile")


@pytest.mark.parametrize("failure", [None, "api", "database", "frontend", "timeout", "redirect"])
def test_public_health_through_gateway(monkeypatch, failure):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        assert request.url.host == "monitor.example.com"
        if failure == "timeout":
            raise httpx.ReadTimeout("internal details must not escape")
        if failure == "redirect":
            return httpx.Response(302, headers={"Location": "https://elsewhere.invalid/"})
        if request.url.path == "/dashboard":
            return httpx.Response(
                200, text="broken" if failure == "frontend" else '<div id="root"></div>'
            )
        bad = (failure == "api" and request.url.path == "/api/health") or (
            failure == "database" and request.url.path == "/api/health/db"
        )
        return httpx.Response(503 if bad else 200, json={"status": "error" if bad else "ok"})

    client = httpx.Client
    monkeypatch.setattr(
        "app.updates.compose.httpx.Client",
        lambda **kw: client(**kw, transport=httpx.MockTransport(handle)),
    )
    if failure:
        with pytest.raises(UpdateError) as error:
            public_health("https://monitor.example.com")
        assert "internal details" not in str(error.value)
    else:
        public_health("https://monitor.example.com")
        assert len(seen) == 3


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.com",
        "https://example.com/private",
        "https://example.com/?token=secret",
    ],
)
def test_public_probe_rejects_non_origin_urls(url):
    with pytest.raises(UpdateError, match="origin"):
        public_health(url)
