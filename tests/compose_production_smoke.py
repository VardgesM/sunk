"""Local disposable production stack: Caddy HTTP/TLS, cookies and WebSocket. No VPS."""

import asyncio
import json
import os
import secrets
import ssl
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import httpx
from compose_auth_helpers import bootstrap_login, ws_headers
from compose_modbus_smoke import free_port
from playwright.async_api import async_playwright
from websockets.asyncio.client import connect


async def main() -> None:
    project = "cloud-production-test-" + uuid4().hex[:10]
    http_port, https_port = free_port(), free_port()
    env = dict(
        os.environ,
        POSTGRES_PASSWORD=secrets.token_urlsafe(32),
        CLOUD_HOST="localhost",
        CLOUD_SCHEME="http",
        CLOUD_PUBLIC_URL=f"http://localhost:{http_port}",
        AUTH_COOKIE_SECURE="false",
        CLOUD_BIND_ADDRESS="127.0.0.1",
        CLOUD_HTTP_PORT=str(http_port),
        CLOUD_HTTPS_PORT=str(https_port),
        MODBUS_WRITES_ENABLED="false",
    )
    prefix = ["docker", "compose", "-p", project, "-f", "docker-compose.cloud.production.yml"]

    async def compose(*args: str) -> str:
        result = await asyncio.to_thread(
            subprocess.run, [*prefix, *args], env=env, capture_output=True, text=True
        )
        if result.returncode:
            raise RuntimeError(f"Compose {args} failed: {result.stderr}")
        return result.stdout

    with TemporaryDirectory(prefix="production-test-", dir=".local") as directory:
        temp = Path(directory).resolve()
        try:
            config = json.loads(await compose("config", "--format", "json"))
            assert set(config["services"]) == {"postgres", "api", "frontend", "migrate"}
            for service in ("postgres", "api", "migrate"):
                assert not config["services"][service].get("ports")
            assert config["networks"]["database"]["internal"]
            assert config["networks"]["backend"]["internal"]
            assert config["services"]["api"]["environment"]["APP_MODE"] == "cloud"
            await compose("up", "-d", "--no-build", "--wait")
            async with httpx.AsyncClient(base_url=env["CLOUD_PUBLIC_URL"], timeout=15) as api:
                username, password = await bootstrap_login(prefix, env, api)
                assert (await api.get("/api/auth/me")).json()["application_mode"] == "cloud"
                runtime = (await api.get("/api/system/runtime")).json()
                assert runtime["application_mode"] == "cloud" and not runtime["alive"]
                assert (await api.get("/dashboard")).status_code == 200
                assert (await api.get("/api/health/db")).status_code == 200
                assert (
                    await api.get("/api/health", headers={"Host": "untrusted.invalid"})
                ).status_code != 200
                async with connect(
                    f"ws://localhost:{http_port}/api/ws/live",
                    additional_headers=ws_headers(api),
                    origin=env["CLOUD_PUBLIC_URL"],
                ) as socket:
                    assert json.loads(await socket.recv())["type"] == "ready"
                assert (
                    await api.post(
                        "/api/auth/login",
                        headers={"Origin": "https://evil.invalid"},
                        json={"username": username, "password": password},
                    )
                ).status_code == 403
            print(
                "PASS: production HTTP/IP-style routing, Cloud-only services, private DB/API, host/origin checks, authenticated WS",
                flush=True,
            )

            # Local CA only: never request public certificates or contact a real domain in tests.
            caddy = (
                Path("deploy/cloud/Caddyfile")
                .read_text()
                .replace("admin off", "admin off\n    skip_install_trust")
            )
            caddy = caddy.replace("{$CLOUD_SITE} {", "{$CLOUD_SITE} {\n    tls internal")
            (temp / "Caddyfile").write_text(caddy)
            override = temp / "tls.json"
            override.write_text(
                json.dumps(
                    {
                        "services": {
                            "frontend": {
                                "volumes": [
                                    {
                                        "type": "bind",
                                        "source": str(temp / "Caddyfile"),
                                        "target": "/etc/caddy/Caddyfile",
                                        "read_only": True,
                                    }
                                ]
                            }
                        }
                    }
                )
            )
            prefix.extend(["-f", str(override)])
            env.update(
                CLOUD_SCHEME="https",
                CLOUD_PUBLIC_URL=f"https://localhost:{https_port}",
                AUTH_COOKIE_SECURE="true",
            )
            await compose("up", "-d", "--no-build", "--force-recreate", "--wait")
            certificate = await compose(
                "exec", "-T", "frontend", "cat", "/data/caddy/pki/authorities/local/root.crt"
            )
            (temp / "root.crt").write_text(certificate)
            context = ssl.create_default_context(cafile=str(temp / "root.crt"))
            async with httpx.AsyncClient(
                base_url=env["CLOUD_PUBLIC_URL"], verify=context, timeout=15
            ) as api:
                response = await api.post(
                    "/api/auth/login", json={"username": username, "password": password}
                )
                assert response.status_code == 200, response.text
                cookies = response.headers.get_list("set-cookie")
                session_cookie = next(c for c in cookies if c.startswith("mm_session="))
                assert all(
                    v in session_cookie.lower()
                    for v in ("secure", "httponly", "samesite=strict", "path=/")
                )
                assert "domain=" not in session_cookie.lower()
                api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
                async with connect(
                    f"wss://localhost:{https_port}/api/ws/live",
                    ssl=context,
                    additional_headers=ws_headers(api),
                    origin=env["CLOUD_PUBLIC_URL"],
                ) as socket:
                    assert json.loads(await socket.recv())["type"] == "ready"
                machine_token = secrets.token_urlsafe(40)
                identity = str(uuid4())
                assert (
                    await api.post(
                        "/api/sync/installations",
                        json={
                            "id": identity,
                            "name": "Isolated production test",
                            "token": machine_token,
                        },
                    )
                ).status_code == 201
                assert (
                    await api.post(
                        "/api/sync/v1/heartbeat",
                        json={"version": 1},
                        headers={"Authorization": "Bearer " + machine_token, "X-Edge-ID": identity},
                    )
                ).status_code == 200
                assert (await api.post("/api/sync/v1/heartbeat", json={})).status_code == 401
                assert (await api.get("/api/sync/status")).json()["edges"][0]["state"] == "ONLINE"
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(channel="msedge", headless=True)
                    try:
                        page = await browser.new_page(
                            ignore_https_errors=True, viewport={"width": 390, "height": 844}
                        )
                        await page.goto(env["CLOUD_PUBLIC_URL"])
                        await page.get_by_label("Username").fill(username)
                        await page.get_by_label("Password").fill(password)
                        await page.get_by_role("button", name="Sign in", exact=True).click()
                        await page.get_by_text("remote monitoring", exact=False).first.wait_for()
                        assert await page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        )
                    finally:
                        await browser.close()
            async with httpx.AsyncClient(follow_redirects=False) as api:
                redirect = await api.get(f"http://localhost:{http_port}/dashboard")
                assert redirect.status_code in (301, 302, 307, 308)
                assert redirect.headers["location"].startswith("https://localhost/")
            await compose("exec", "-T", "api", "alembic", "check")
            assert "0014_backups" in await compose("exec", "-T", "api", "alembic", "current")
            assert (await compose("exec", "-T", "frontend", "id", "-u")).strip() == "1000"
            logs = await compose("logs", "--no-color", "api", "frontend", "migrate")
            assert env["POSTGRES_PASSWORD"] not in logs and machine_token not in logs
            assert "Traceback" not in logs
            print(
                "PASS: trusted local TLS, Secure/HttpOnly/Strict cookies, WSS, production browser assets, machine heartbeat, HTTPS redirect, Alembic, non-root proxy",
                flush=True,
            )
        except Exception:
            logs = await compose("logs", "--no-color", "frontend", "migrate", "api")
            print(logs[-9000:].replace(env["POSTGRES_PASSWORD"], "[redacted]"), flush=True)
            raise
        finally:
            await compose("down", "-v", "--remove-orphans")
            print("Removed isolated production test containers and volumes", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
