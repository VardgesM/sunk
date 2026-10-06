"""Only named GitHub Release assets; never source archives, arbitrary URLs or scripts."""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.updates.schema import Release, ReleaseManifest, semver
from app.updates.store import UpdateError

HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


class GitHubReleases:
    def __init__(self, repository: str, client: httpx.AsyncClient):
        if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
            raise UpdateError("Invalid GitHub repository configuration")
        self.repository, self.client = repository, client

    def asset_url(self, tag: str, name: str) -> str:
        semver(tag.removeprefix("v"))
        return f"https://github.com/{self.repository}/releases/download/{tag}/{name}"

    async def fetch(self, url: str, maximum: int, destination: Path | None = None) -> bytes:
        for _ in range(5):
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname
                not in {
                    "api.github.com",
                    "github.com",
                    "release-assets.githubusercontent.com",
                    "objects.githubusercontent.com",
                }
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                raise UpdateError("Untrusted release download destination")
            async with self.client.stream(
                "GET", url, headers=HEADERS, follow_redirects=False
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                data = bytearray()
                size = 0
                output = destination.open("xb") if destination else None
                try:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > maximum:
                            raise UpdateError("Release download exceeds configured size limit")
                        if output:
                            output.write(chunk)
                        else:
                            data.extend(chunk)
                finally:
                    if output:
                        output.close()
                return bytes(data)
        raise UpdateError("Too many release download redirects")

    async def latest(self) -> Release | None:
        try:
            data = json.loads(
                await self.fetch(
                    f"https://api.github.com/repos/{self.repository}/releases/latest", 2 * 1024**2
                )
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        if data.get("draft") or data.get("prerelease"):
            raise UpdateError("Only published stable releases are supported")
        tag = data["tag_name"]
        version = tag.removeprefix("v")
        semver(version)
        names = {asset["name"]: asset for asset in data["assets"]}
        archive_name = f"modbus-monitor-{version}.tar.gz"
        manifest_name = f"modbus-monitor-{version}.json"
        if archive_name not in names or manifest_name not in names:
            raise UpdateError("Release has no supported application artifact and manifest")
        manifest = ReleaseManifest.model_validate_json(
            await self.fetch(self.asset_url(tag, manifest_name), 8 * 1024**2)
        )
        if manifest.version != version or names[archive_name]["size"] != manifest.size:
            raise UpdateError("Release metadata does not match manifest")
        digest = names[archive_name].get("digest")
        if digest and digest != "sha256:" + manifest.sha256:
            raise UpdateError("GitHub asset digest does not match release manifest")
        return Release(
            version=version,
            tag=tag,
            published_at=data["published_at"],
            notes=data.get("body") or "",
            manifest=manifest,
        )

    async def download(self, release: Release, destination: Path) -> None:
        await self.fetch(
            self.asset_url(release.tag, f"modbus-monitor-{release.version}.tar.gz"),
            release.manifest.size,
            destination,
        )
