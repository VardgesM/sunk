"""Fail the one-shot migration gate on unsafe or inconsistent Cloud configuration."""

import os
from urllib.parse import urlsplit

from app.core.config import Settings


def validate(settings: Settings, host: str, scheme: str, public_url: str) -> None:
    url = urlsplit(public_url)
    if settings.application_mode != "cloud" or settings.source_mode != "disabled":
        raise ValueError("Production Cloud requires APP_MODE=cloud and disabled telemetry")
    if scheme not in ("http", "https") or url.scheme != scheme or url.hostname != host:
        raise ValueError("Cloud scheme, host and public URL must match")
    if url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("Cloud public URL must be an origin without credentials or path")
    if not host or any(not (c.isalnum() or c in ".-") for c in host):
        raise ValueError("Invalid Cloud host")
    if settings.auth_cookie_secure != (scheme == "https"):
        raise ValueError("HTTPS requires secure cookies; HTTP test mode requires insecure cookies")
    if "*" in settings.allowed_hosts or host not in settings.allowed_hosts:
        raise ValueError("Explicit allowed hosts are required")
    if settings.cors_origins != [public_url.rstrip("/")]:
        raise ValueError("Allow exactly the public origin for browser and WebSocket access")


def main() -> None:
    try:
        validate(
            Settings(),
            os.environ.get("CLOUD_HOST", ""),
            os.environ.get("CLOUD_SCHEME", "https"),
            os.environ.get("CLOUD_PUBLIC_URL", ""),
        )
    except (ValueError, TypeError):
        raise SystemExit(
            "Cloud preflight failed. Check mode, host, URL, cookie and database settings; see production documentation."
        ) from None
    print("Cloud production configuration validated")


if __name__ == "__main__":
    main()
