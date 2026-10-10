"""Opt-in Cloud host handler. Pinned operator-owned topology, no Docker socket in API."""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from app.schemas.backup import Strict
from app.updates.artifact import disk_space, sha256, unpack
from app.updates.schema import UpdateStatus
from app.updates.store import UpdateError, UpdateStore, atomic_json


def public_health(url: str) -> None:
    """Verify the operator-configured origin, including the independent gateway route."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise UpdateError("Invalid configured public origin")
    try:
        with httpx.Client(base_url=url.rstrip("/"), timeout=5, follow_redirects=False) as client:
            for path in ("/api/health", "/api/health/db"):
                response = client.get(path)
                if response.status_code != 200 or response.json().get("status") != "ok":
                    raise UpdateError("Public API/database health check failed")
            response = client.get("/dashboard")
            if response.status_code != 200 or '<div id="root">' not in response.text:
                raise UpdateError("Public frontend health check failed")
    except (httpx.HTTPError, ValueError):
        raise UpdateError("Public gateway health check failed") from None


def validate_topology(config: dict) -> None:
    services = config["services"]
    if set(services) != {"api", "frontend", "postgres", "migrate"}:
        raise UpdateError("Unsupported deployment topology; gateway must be a separate project")
    if any(services[name].get("ports") for name in services):
        raise UpdateError("Application services must not publish ports; migrate the gateway first")
    if not config.get("networks", {}).get("web", {}).get("external"):
        raise UpdateError("Cloud requires an operator-managed external gateway network")
    if set(services["postgres"].get("networks", {})) != {"database"}:
        raise UpdateError("PostgreSQL must remain on its private database network")
    if not config.get("networks", {}).get("database", {}).get("internal"):
        raise UpdateError("PostgreSQL network must be internal")
    for service in services.values():
        if any(
            v.get("target") in {"/data", "/config", "/var/run/docker.sock"}
            for v in service.get("volumes", [])
        ):
            raise UpdateError("Application deployment must not own gateway state or Docker socket")


class HostConfig(Strict):
    handler: Literal["cloud-compose-v1"]
    project_name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    project_directory: Path
    compose_files: list[Path] = Field(min_length=1, max_length=4)
    env_file: Path
    shared_directory: Path
    private_directory: Path
    command_timeout_seconds: int = Field(default=1800, ge=30, le=7200)
    health_timeout_seconds: int = Field(default=120, ge=10, le=600)
    disk_reserve_mb: int = Field(default=4096, ge=256)

    @model_validator(mode="after")
    def paths(self) -> "HostConfig":
        paths = [
            self.project_directory,
            self.env_file,
            self.shared_directory,
            self.private_directory,
            *self.compose_files,
        ]
        if any(not path.is_absolute() or path.is_symlink() for path in paths):
            raise ValueError("Host configuration requires absolute non-symlink paths")
        shared, private = self.shared_directory.resolve(), self.private_directory.resolve()
        if shared == private or shared in private.parents or private in shared.parents:
            raise ValueError("Host private state must be separate from API shared state")
        if any(
            shared == p.resolve() or shared in p.resolve().parents
            for p in [self.env_file, *self.compose_files]
        ):
            raise ValueError("Deployment configuration must be outside API shared storage")
        return self


class CloudCompose:
    def __init__(self, config: HostConfig, store: UpdateStore):
        self.config, self.store = config, store
        config.private_directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def run(self, arguments: list[str], *, capture: bool = False) -> str:
        try:
            result = subprocess.run(
                arguments,
                cwd=self.config.project_directory,
                shell=False,
                check=True,
                timeout=self.config.command_timeout_seconds,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
            )
            return result.stdout or ""
        except (OSError, subprocess.SubprocessError):
            raise UpdateError(
                "Deployment command failed; inspect service health on the host"
            ) from None

    def compose(self, extra: Path | None, *args: str, capture: bool = False) -> str:
        command = [
            "docker",
            "compose",
            "--project-name",
            self.config.project_name,
            "--project-directory",
            str(self.config.project_directory),
            "--env-file",
            str(self.config.env_file),
        ]
        for path in self.config.compose_files:
            command.extend(["-f", str(path)])
        if extra:
            command.extend(["-f", str(extra)])
        return self.run([*command, *args], capture=capture)

    def work(self, status: UpdateStatus) -> Path:
        path = self.config.private_directory / str(status.job_id)
        if path.is_symlink():
            raise UpdateError("Unsafe private deployment directory")
        path.mkdir(mode=0o700, exist_ok=True)
        return path

    def fingerprint(self) -> dict:
        return {
            str(path): sha256(path) for path in [self.config.env_file, *self.config.compose_files]
        }

    def unchanged(self, status: UpdateStatus) -> dict:
        metadata = json.loads((self.work(status) / "deployment.json").read_text("utf-8"))
        if metadata["fingerprint"] != self.fingerprint():
            raise UpdateError(
                "Deployment settings changed during update; operator recovery required"
            )
        return metadata

    def probe(self, extra: Path | None = None) -> dict:
        return json.loads(
            self.compose(
                extra, "exec", "-T", "api", "python", "-m", "app.update_health", capture=True
            )
        )

    def preserve_and_build(self, status: UpdateStatus) -> None:
        work = self.work(status)
        disk_space(work, self.config.disk_reserve_mb * 1024**2)
        if not status.backup_id or not (self.store.job(status.job_id) / "recovery.mmbak").is_file():
            raise UpdateError("Encrypted pre-update backup is required")
        if sha256(self.store.job(status.job_id) / "recovery.mmbak") != status.backup_sha256:
            raise UpdateError("Pinned recovery backup integrity check failed")
        config = json.loads(self.compose(None, "config", "--format", "json", capture=True))
        validate_topology(config)
        services = config["services"]
        if set(services) != {"api", "frontend", "postgres", "migrate"}:
            raise UpdateError(
                "Unsupported deployment topology; only production Cloud Compose is supported"
            )
        environment = services["api"]["environment"]
        if (
            environment.get("APP_MODE") != "cloud"
            or environment.get("TELEMETRY_SOURCE") != "disabled"
        ):
            raise UpdateError("Cloud updater cannot manage hardware or Automation services")
        if services["api"].get("ports") or services["postgres"].get("ports"):
            raise UpdateError("Cloud database/API ports must remain private")
        running_services = self.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={self.config.project_name}",
                "--format",
                '{{.Label "com.docker.compose.service"}}',
            ],
            capture=True,
        ).splitlines()
        if any(service not in {"api", "frontend", "postgres"} for service in running_services):
            raise UpdateError("Unexpected active services in the Cloud project")
        probe = self.probe()
        public_health(environment["CLOUD_PUBLIC_URL"])
        if (
            probe["version"] != status.from_version
            or probe["revision"] != status.previous_revision
            or probe["mode"] != "cloud"
        ):
            raise UpdateError("Running application changed since backup; prepare a new update")
        images = {}
        for service in ("api", "frontend", "postgres"):
            container = self.compose(None, "ps", "--all", "-q", service, capture=True).strip()
            if not re.fullmatch(r"[a-f0-9]{12,64}", container):
                raise UpdateError("Expected exactly one container per Cloud service")
            details = json.loads(self.run(["docker", "inspect", container], capture=True))[0]
            mounts = {mount["Destination"]: mount for mount in details["Mounts"]}
            for volume in services[service].get("volumes", []):
                mount = mounts.get(volume["target"], {})
                expected_source = volume["source"]
                if volume["type"] == "volume":
                    expected_source = config["volumes"][expected_source]["name"]
                    actual_source = mount.get("Name")
                else:
                    actual_source = mount.get("Source")
                same_source = actual_source == expected_source
                if volume["type"] == "bind" and actual_source:
                    same_source = Path(actual_source).resolve() == Path(expected_source).resolve()
                if mount.get("Type") != volume["type"] or not same_source:
                    raise UpdateError("Persistent storage differs from the running deployment")
            if service == "api":
                shared = mounts.get("/var/lib/modbus-monitor/updates", {})
                if (
                    not shared.get("Source")
                    or Path(shared["Source"]).resolve() != self.config.shared_directory.resolve()
                ):
                    raise UpdateError("Runner and API do not share the same updater journal")
                actual = dict(item.split("=", 1) for item in details["Config"]["Env"])
                if any(str(value) != actual.get(key) for key, value in environment.items()):
                    raise UpdateError(
                        "Environment differs from running API; resolve configuration before updating"
                    )
                # Already-applied migrations may not be modified by a release.
                self.run(
                    [
                        "docker",
                        "cp",
                        f"{container}:/app/alembic/versions",
                        str(work / "previous-migrations"),
                    ]
                )
            images[service] = details["Image"]
        prefix = "modbus-retained-" + str(status.job_id)
        previous = {"services": {}}
        for service in ("api", "frontend"):
            tag = prefix + ":" + service
            self.run(["docker", "image", "tag", images[service], tag])
            previous["services"][service] = {"image": tag}
        previous["services"]["migrate"] = {"image": prefix + ":api"}
        atomic_json(work / "previous.json", previous)
        atomic_json(
            work / "deployment.json",
            {
                "fingerprint": self.fingerprint(),
                "probe": probe,
                "public_url": environment["CLOUD_PUBLIC_URL"],
            },
        )
        release_root = work / "release"
        unpack(
            self.store.job(status.job_id) / "release.tar.gz",
            status.release.manifest,
            release_root,
            status.from_version,
        )
        for old in (work / "previous-migrations").glob("*.py"):
            new = release_root / "server/alembic/versions" / old.name
            # Python normalizes source newlines on import. Git autocrlf must not look like
            # an applied migration edit when a release is packaged on Windows for Linux.
            if not new.is_file() or old.read_bytes().replace(
                b"\r\n", b"\n"
            ) != new.read_bytes().replace(b"\r\n", b"\n"):
                raise UpdateError("Release modifies an existing migration")
        next_prefix = "modbus-release-" + str(status.job_id)
        overrides = {
            "services": {
                "api": {
                    "image": next_prefix + ":api",
                    "build": {"context": str(release_root / "server")},
                },
                "migrate": {
                    "image": next_prefix + ":api",
                    "build": {"context": str(release_root / "server")},
                },
                "frontend": {
                    "image": next_prefix + ":frontend",
                    "build": {
                        "context": str(release_root),
                        "dockerfile": "frontend/Dockerfile.production",
                    },
                },
            }
        }
        atomic_json(work / "next.json", overrides)
        self.compose(work / "next.json", "build", "api", "frontend")
        self.unchanged(status)

    def stop(self, status: UpdateStatus) -> None:
        # No down/rm/prune, no volumes removed, no database restart. Works before/after redeploy.
        self.compose(None, "stop", "--timeout", "30", "api", "frontend")
        self.stop_migration(status)

    def stop_migration(self, status: UpdateStatus) -> None:
        name = "mm-migration-" + str(status.job_id)
        if self.run(["docker", "ps", "-aq", "--filter", f"name=^/{name}$"], capture=True).strip():
            self.run(["docker", "rm", "-f", name])

    def migrate(self, status: UpdateStatus) -> None:
        self.unchanged(status)
        name = "mm-migration-" + str(status.job_id)
        try:
            self.compose(
                self.work(status) / "next.json",
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--name",
                name,
                "migrate",
            )
        finally:
            # A timed-out Docker CLI can leave its one-shot container running. Stop only this job.
            self.stop_migration(status)

    def start(self, status: UpdateStatus, *, previous: bool = False) -> None:
        self.unchanged(status)
        override = self.work(status) / ("previous.json" if previous else "next.json")
        self.compose(
            override,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(self.config.health_timeout_seconds),
            "api",
            "frontend",
        )

    def verify(self, status: UpdateStatus, *, previous: bool = False) -> None:
        metadata = self.unchanged(status)
        expected = dict(metadata["probe"])
        if not previous:
            expected.update(
                version=status.release.version, revision=status.release.manifest.migration_revision
            )
        if self.probe() != expected:
            raise UpdateError("Version, migration, mode or write safety health check failed")
        deadline = time.monotonic() + self.config.health_timeout_seconds
        while True:
            try:
                public_health(metadata["public_url"])
                break
            except UpdateError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        atomic_json(
            self.config.private_directory / "active.json",
            {
                "job_id": str(status.job_id),
                "override": "previous.json" if previous else "next.json",
                "version": expected["version"],
            },
        )
