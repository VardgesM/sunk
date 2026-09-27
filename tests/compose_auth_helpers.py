"""Test-only bootstrap over stdin, authenticated API/socket/browser clients."""

import asyncio
import json
import secrets
import subprocess


async def bootstrap_login(prefix, environment, api) -> tuple[str, str]:
    username, password = "integration_admin", secrets.token_urlsafe(24)
    code = "import asyncio,json,sys; from app.bootstrap import bootstrap; asyncio.run(bootstrap(*json.load(sys.stdin)))"
    result = await asyncio.to_thread(
        subprocess.run,
        [*prefix, "exec", "-T", "api", "python", "-c", code],
        input=json.dumps([username, password]),
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("Isolated authentication bootstrap failed: " + result.stderr)
    url = api.base_url.copy_with(path="/api/auth/login")
    response = await api.post(url, json={"username": username, "password": password})
    response.raise_for_status()
    api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
    return username, password


def ws_headers(api):
    return {"Cookie": "; ".join(f"{key}={value}" for key, value in api.cookies.items())}


async def browser_session(page, api):
    await page.context.add_cookies(
        [
            {
                "name": key,
                "value": value,
                "domain": "localhost",
                "path": "/",
                "httpOnly": key == "mm_session",
                "sameSite": "Strict",
                "secure": False,
            }
            for key, value in api.cookies.items()
        ]
    )


async def login_existing(api) -> None:
    """Interactive opt-in helpers authenticate without accepting secrets in CLI arguments."""
    from getpass import getpass

    username = input("Test ADMIN username: ").strip()
    password = getpass("Test ADMIN password: ")
    response = await api.post("/api/auth/login", json={"username": username, "password": password})
    response.raise_for_status()
    if response.json()["role"] != "ADMIN":
        raise RuntimeError("This configuration integration requires an ADMIN")
    api.headers["X-CSRF-Token"] = api.cookies["mm_csrf"]
    runtime = await api.get("/api/system/runtime")
    runtime.raise_for_status()
    if runtime.json()["mode"] != "simulator":
        raise RuntimeError("This opt-in integration requires an explicitly configured simulator worker")
