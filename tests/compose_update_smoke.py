"""Opt-in, isolated Cloud deployment/rollback rehearsal. No production volumes or hardware.

Builds unique images; creates a unique Compose project; only its labelled volumes are removed.
GitHub is replaced with locally built release fixtures. No release is published or downloaded.
Run from repository root: python tests/compose_update_smoke.py
"""

import asyncio
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import httpx
from compose_auth_helpers import bootstrap_login

from app.core.version import APP_VERSION
from app.release import build
from app.updates.artifact import sha256
from app.updates.compose import CloudCompose, HostConfig
from app.updates.engine import install
from app.updates.schema import Release, UpdateStatus
from app.updates.store import UpdateStore, atomic_json

ROOT = Path(__file__).resolve().parents[1]


def port() -> int:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def command(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if check and result.returncode:
        raise RuntimeError("Isolated Docker operation failed; subprocess output suppressed")
    return result.stdout.strip()


async def main() -> None:
    project = "update-smoke-" + uuid4().hex[:10]
    images: list[str] = []
    with TemporaryDirectory(prefix="updater-smoke-", dir=ROOT / ".local") as temporary:
        work = Path(temporary)
        shared, private = work / "shared", work / "private"
        shared.mkdir()
        private.mkdir()
        environment = work / "cloud.env"
        http_port = port()
        values = {
            "POSTGRES_DB": "update_smoke",
            "POSTGRES_USER": "update_smoke",
            "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "CLOUD_HOST": "localhost",
            "CLOUD_SCHEME": "http",
            "CLOUD_PUBLIC_URL": f"http://localhost:{http_port}",
            "AUTH_COOKIE_SECURE": "false",
            "MODBUS_WRITES_ENABLED": "false",
            "CLOUD_BIND_ADDRESS": "127.0.0.1",
            "CLOUD_HTTP_PORT": str(http_port),
            "CLOUD_HTTPS_PORT": str(port()),
            "UPDATE_SHARED_DIRECTORY": shared.as_posix(),
        }
        os.environ.update(values)  # This disposable test process only; no real env file is read.
        environment.write_text(
            "\n".join(f"{key}={value}" for key, value in values.items()), encoding="utf-8"
        )
        os.chmod(environment, 0o600)
        image_override = work / "images.json"
        api_image, frontend_image = project + ":api", project + ":frontend"
        images.extend([api_image, frontend_image])
        atomic_json(
            image_override,
            {
                "services": {
                    "api": {"image": api_image},
                    "migrate": {"image": api_image},
                    "frontend": {"image": frontend_image},
                }
            },
        )
        config = HostConfig(
            handler="cloud-compose-v1",
            project_name=project,
            project_directory=ROOT,
            compose_files=[
                ROOT / "docker-compose.cloud.production.yml",
                ROOT / "deploy/update/cloud.compose.yml",
                image_override,
            ],
            env_file=environment,
            shared_directory=shared,
            private_directory=private,
        )
        prefix = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(environment),
        ]
        for file in config.compose_files:
            prefix.extend(["-f", str(file)])
        try:
            rendered = json.loads(command([*prefix, "config", "--format", "json"]))
            assert set(rendered["services"]) == {"postgres", "migrate", "api", "frontend"}
            assert not rendered["services"]["postgres"].get("ports")
            assert not rendered["services"]["api"].get("ports")
            assert rendered["services"]["api"]["environment"]["MODBUS_WRITES_ENABLED"] == "false"
            command([*prefix, "build", "api", "frontend"])
            command([*prefix, "up", "-d", "--no-build", "--wait", "--wait-timeout", "150"])
            # Create a reviewed local release fixture without touching the working checkout.
            source = work / "release-source"
            tracked = command(
                [
                    "git",
                    "-c",
                    f"safe.directory={ROOT.as_posix()}",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    "server",
                    "frontend",
                    "deploy/cloud/Caddyfile",
                ]
            ).splitlines()
            for name in tracked:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            canonical = source / "server/pyproject.toml"
            major, minor, patch = (int(part) for part in APP_VERSION.split("."))
            next_version = f"{major}.{minor}.{patch + 1}"
            canonical.write_text(
                re.sub(
                    r'(?m)^version = "[^"]+"',
                    f'version = "{next_version}"',
                    canonical.read_text("utf-8"),
                    count=1,
                ),
                encoding="utf-8",
            )
            manifest = build(source, work / "artifacts", APP_VERSION, tracked)
            release = Release(
                version=next_version,
                tag="v" + next_version,
                published_at=datetime.now(UTC),
                notes="Isolated deployment test",
                manifest=manifest,
            )
            env_before = environment.read_bytes()
            store = UpdateStore(shared)
            async with httpx.AsyncClient(base_url=values["CLOUD_PUBLIC_URL"], timeout=120) as api:
                await bootstrap_login(prefix, dict(os.environ), api)
                response = await api.post(
                    "/api/system/backups", json={"passphrase": "isolated-smoke-passphrase"}
                )
                response.raise_for_status()
                backup = response.json()
                response = await api.get(f"/api/system/backups/{backup['id']}/download")
                response.raise_for_status()
                encrypted = response.content
                assert encrypted.startswith(b"MMBACKUP")
                for fail_health in (True, False):
                    status = UpdateStatus(
                        installed_version=APP_VERSION,
                        from_version=APP_VERSION,
                        state="READY",
                        job_id=uuid4(),
                        release=release,
                        backup_id=UUID(backup["id"]),
                        previous_revision=backup["manifest"]["migration_revision"],
                    )
                    folder = store.job(status.job_id)
                    shutil.copyfile(
                        work / f"artifacts/modbus-monitor-{next_version}.tar.gz",
                        folder / "release.tar.gz",
                    )
                    (folder / "recovery.mmbak").write_bytes(encrypted)
                    status.backup_sha256 = sha256(folder / "recovery.mmbak")
                    store.write(status)
                    deployment = CloudCompose(config, store)
                    original_verify = deployment.verify
                    if fail_health:

                        def verify(current, *, previous=False):
                            if not previous:
                                raise RuntimeError("Injected health verification failure")
                            original_verify(current, previous=True)

                        deployment.verify = verify
                    images.extend(
                        [
                            f"modbus-{kind}-{status.job_id}:{service}"
                            for kind in ("retained", "release")
                            for service in ("api", "frontend")
                        ]
                    )
                    await asyncio.to_thread(install, store, status, deployment)
                    result = store.read()
                    expected = "ROLLED_BACK" if fail_health else "SUCCESS"
                    assert result.state == expected, result.model_dump_json(exclude={"release"})
                    assert environment.read_bytes() == env_before
                    assert (folder / "recovery.mmbak").read_bytes() == encrypted
                    probe = await asyncio.to_thread(deployment.probe)
                    assert probe["version"] == (APP_VERSION if fail_health else next_version)
                    assert probe["mode"] == "cloud" and not probe["writes_enabled"]
                    response = await api.get("/api/system/updates/status")
                    response.raise_for_status()
                    assert response.json()["state"] == expected
                    assert (await api.get("/dashboard")).status_code == 200
                    print(
                        f"PASS: {expected}, API/database/version, frontend, session, encrypted backup, unchanged env and Cloud-only topology",
                        flush=True,
                    )
            print(
                "PASS: isolated Compose updater build, real PostgreSQL backup, binary rollback and successful redeploy",
                flush=True,
            )
        finally:
            command([*prefix, "down", "--remove-orphans"], check=False)
            # Never down -v. Delete only volumes positively labelled for this generated test project.
            volumes = command(
                [
                    "docker",
                    "volume",
                    "ls",
                    "-q",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                ],
                check=False,
            ).splitlines()
            for volume in volumes:
                if volume.startswith(project + "_"):
                    command(["docker", "volume", "rm", volume], check=False)
            for image in images:
                command(["docker", "image", "rm", image], check=False)


if __name__ == "__main__":
    asyncio.run(main())
