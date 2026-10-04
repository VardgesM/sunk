"""Opt-in Docker regression: build real images from a 0600/0700 source context.

Run from the repository root: python tests/docker_permissions_smoke.py
Uses only tracked sources and synthetic .env canaries, never the host's real .env.
Unique images/containers/network and a tmpfs database are removed on exit.
"""

import io
import json
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def docker(*args: str, data: bytes | None = None, check: bool = True) -> str:
    result = subprocess.run(
        ["docker", *args], input=data, capture_output=True, cwd=ROOT, timeout=900
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-8000:])
    output = result.stdout + (result.stderr if args[0] == "logs" else b"")
    return output.decode(errors="replace").strip()


def restricted_context(folder: str) -> bytes:
    """TAR modes reproduce Linux umask 077 even when this test runs on Windows."""
    tracked = (
        subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )
    files: dict[str, bytes] = {}
    for name in filter(None, tracked):
        if folder:
            if not name.startswith(folder + "/"):
                continue
            relative = name.removeprefix(folder + "/")
        else:
            if not (name.startswith(("frontend/", "deploy/cloud/")) or name == ".dockerignore"):
                continue
            relative = name
        files[relative] = (ROOT / name).read_bytes()
    directories = {
        parent.as_posix()
        for name in files
        for parent in PurePosixPath(name).parents
        if parent != PurePosixPath(".")
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name in sorted(directories):
            entry = tarfile.TarInfo(name)
            entry.type, entry.mode = tarfile.DIRTYPE, 0o700
            archive.addfile(entry)
        for name, content in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.mode, entry.size = 0o600, len(content)
            archive.addfile(entry, io.BytesIO(content))
    return stream.getvalue()


def wait_ready(container: str, *command: str) -> None:
    for _ in range(60):
        result = subprocess.run(
            ["docker", "exec", container, *command], capture_output=True, timeout=15
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError(f"{container} did not become ready: {docker('logs', container)[-4000:]}")


def main() -> None:
    prefix = "permissions-test-" + uuid4().hex[:10]
    images: list[str] = []
    containers: list[str] = []
    network_created = False

    def start(name: str, image: str, *options: str) -> str:
        container = prefix + "-" + name
        containers.append(container)
        docker("run", "-d", "--name", container, "--network", prefix, *options, image)
        return container

    try:
        for name, folder, dockerfile in (
            ("server", "server", "Dockerfile"),
            ("dev", "frontend", "Dockerfile"),
            ("web", "", "frontend/Dockerfile.production"),
        ):
            image = prefix + "-" + name
            docker(
                "build",
                "--progress=plain",
                "-t",
                image,
                "-f",
                dockerfile,
                "-",
                data=restricted_context(folder),
            )
            images.append(image)
            print(f"PASS: {name} image built from files=0600, directories=0700", flush=True)

        server, dev, web = images
        # A TAR sent over stdin bypasses client-side .dockerignore filtering. Check
        # each real ignore file separately with a normal directory build context.
        for index, folder in enumerate(("server", "frontend", ".")):
            with TemporaryDirectory(prefix="permissions-ignore-") as directory:
                context = Path(directory)
                (context / ".dockerignore").write_bytes(
                    (ROOT / folder / ".dockerignore").read_bytes()
                )
                for name in (".env", ".env.cloud"):
                    (context / name).write_text("PERMISSIONS_TEST_CANARY=not-a-real-secret\n")
                (context / "Dockerfile").write_text(
                    f"FROM {server}\nUSER root\nWORKDIR /ignore-check\nCOPY . .\n"
                    "RUN test ! -e .env && test ! -e .env.cloud\n"
                )
                image = prefix + f"-ignore-{index}"
                docker("build", "-t", image, str(context))
                images.append(image)
        print("PASS: all three normal build contexts exclude synthetic .env/.env.cloud", flush=True)
        docker(
            "run",
            "--rm",
            server,
            "python",
            "-c",
            """
import os
import stat
from pathlib import Path
from app.core.config import Settings
from app.main import create_app
import app.worker
import app.sync
assert os.getuid() != 0
for root in (Path('/app/app'), Path('/app/alembic')):
    for path in [root, *root.rglob('*')]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o755 if path.is_dir() else 0o644), path
        assert os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0)), path
for name in ('pyproject.toml', 'alembic.ini'):
    assert stat.S_IMODE(Path('/app', name).stat().st_mode) == 0o644
assert stat.S_IMODE(Path('/var/lib/modbus-monitor/backups').stat().st_mode) == 0o700
assert not list(Path('/app').rglob('.env*'))
create_app(Settings(_env_file=None, postgres_password='isolated-test-only'))
""",
        )
        docker(
            "run",
            "--rm",
            dev,
            "node",
            "-e",
            """
const fs = require('node:fs');
const assert = require('node:assert/strict');
assert.notEqual(process.getuid(), 0);
for (const name of fs.readdirSync('/app/src', {recursive: true})) {
    const path = '/app/src/' + name;
    if (fs.statSync(path).isFile()) fs.readFileSync(path);
}
for (const name of ['package.json', 'index.html', 'tsconfig.json', 'vite.config.ts']) {
    fs.readFileSync('/app/' + name);
}
assert(!fs.readdirSync('/app', {recursive: true}).some(n => n.split('/').at(-1).startsWith('.env')));
""",
        )
        docker(
            "run",
            "--rm",
            "-e",
            "CLOUD_SITE=http://localhost",
            web,
            "sh",
            "-ec",
            'test "$(id -u)" != 0; test -r /etc/caddy/Caddyfile; '
            'test -r /srv/index.html; test -z "$(find /srv -name ".env*")"; '
            "caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile",
        )
        print(
            "PASS: non-root imports/source access; private directory unchanged; .env excluded",
            flush=True,
        )

        docker("network", "create", prefix)
        network_created = True
        database = start(
            "db",
            "postgres:17-alpine",
            "--network-alias",
            "postgres",
            "--tmpfs",
            "/var/lib/postgresql/data",
            "-e",
            "POSTGRES_PASSWORD=isolated-test-only",
        )
        wait_ready(database, "pg_isready", "-h", "127.0.0.1", "-U", "postgres")
        environment = [
            "-e",
            "POSTGRES_HOST=postgres",
            "-e",
            "POSTGRES_DB=postgres",
            "-e",
            "POSTGRES_USER=postgres",
            "-e",
            "POSTGRES_PASSWORD=isolated-test-only",
            "-e",
            "APP_MODE=cloud",
            "-e",
            "TELEMETRY_SOURCE=disabled",
            "-e",
            "MODBUS_WRITES_ENABLED=false",
            "-e",
            "TELEGRAM_ENABLED=false",
        ]
        for command in (("upgrade", "head"), ("check",)):
            docker("run", "--rm", "--network", prefix, *environment, server, "alembic", *command)
        print(
            "PASS: non-root Alembic upgrade head + check against disposable PostgreSQL", flush=True
        )
        api = start("api", server, "--network-alias", "api", *environment)
        wait_ready(
            api,
            "python",
            "-c",
            "import urllib.request; "
            "urllib.request.urlopen('http://localhost:8000/api/health/db', timeout=5)",
        )
        vite = start("dev", dev)
        wait_ready(
            vite,
            "node",
            "-e",
            "fetch('http://localhost:5173/src/main.tsx')"
            ".then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))",
        )
        caddy = start(
            "web",
            web,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "-e",
            "CLOUD_SITE=http://localhost",
        )
        wait_ready(caddy, "wget", "-qO-", "http://localhost:8080/")
        html = docker("exec", caddy, "wget", "-qO-", "http://localhost:8080/")
        assert '<div id="root">' in html
        assert (
            json.loads(
                docker("exec", caddy, "wget", "-qO-", "http://localhost:8080/api/health/db")
            )["status"]
            == "ok"
        )
        assets = docker("exec", caddy, "find", "/srv/assets", "-type", "f").splitlines()
        assert assets
        for asset in assets:
            docker(
                "exec",
                caddy,
                "wget",
                "-qO",
                "/dev/null",
                "http://localhost:8080" + asset.removeprefix("/srv"),
            )
        for container in (api, vite, caddy):
            logs = docker("logs", container)
            assert "PermissionError" not in logs and "Permission denied" not in logs
        print("PASS: API DB health, Vite TSX serving, non-root Caddy SPA/API routing", flush=True)
    finally:
        for container in reversed(containers):
            docker("rm", "-f", "-v", container, check=False)
        if network_created:
            docker("network", "rm", prefix)
        for image in reversed(images):
            docker("image", "rm", image)
        print("Removed only this test's isolated containers, network and images", flush=True)


if __name__ == "__main__":
    main()
