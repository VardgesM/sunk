"""Data-only validation. Never import or execute downloaded Python during validation."""

import ast
import gzip
import hashlib
import os
import shutil
import tarfile
import tomllib
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryFile

from app.updates.schema import ReleaseManifest, semver
from app.updates.store import UpdateError

MAX_EXPANDED = 1024**3


def permitted(name: str) -> bool:
    path = PurePosixPath(name)
    if (
        len(name) > 1024
        or len(path.parts) > 20
        or any(
            PureWindowsPath(part).is_reserved() or part.endswith((".", " ")) for part in path.parts
        )
    ):
        return False
    if path.is_absolute() or "\\" in name or ":" in name or ".." in path.parts:
        return False
    if str(path) != name or any(
        part.startswith(".") and part != ".dockerignore" for part in path.parts
    ):
        return False
    forbidden = {"node_modules", "__pycache__", "dist", "backups", "logs", ".venv"}
    if any(part in forbidden or part.endswith(".egg-info") for part in path.parts):
        return False
    if path.suffix.lower() in {".dump", ".mmbak", ".pem", ".key", ".pyc", ".db", ".sqlite"}:
        return False
    return name.startswith(("server/", "frontend/"))


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def disk_space(path: Path, needed: int) -> None:
    if shutil.disk_usage(path).free < needed:
        raise UpdateError("Insufficient free disk space for release and recovery reserve")


def unpack(archive: Path, manifest: ReleaseManifest, target: Path, installed: str) -> None:
    if semver(manifest.version) <= semver(installed):
        raise UpdateError("Release must be newer than the installed version")
    if semver(installed) < semver(manifest.minimum_version):
        raise UpdateError("Release requires an intermediate application update")
    if (
        archive.is_symlink()
        or archive.stat().st_size != manifest.size
        or sha256(archive) != manifest.sha256
    ):
        raise UpdateError("Release checksum or size mismatch")
    total = sum(entry.size for entry in manifest.files.values())
    if total > MAX_EXPANDED or not all(permitted(name) for name in manifest.files):
        raise UpdateError("Release contains forbidden paths or exceeds size limits")
    disk_space(target.parent, total * 2 + 64 * 1024**2)
    target.mkdir(mode=0o700, exist_ok=False)
    seen = set()
    try:
        # Bound decompression before TAR parses extension headers (including malicious PAX sizes).
        with TemporaryFile(dir=target.parent) as raw:
            expanded = 0
            with gzip.open(archive, "rb") as compressed:
                while chunk := compressed.read(1024**2):
                    expanded += len(chunk)
                    if expanded > total + len(manifest.files) * 4096 + 65536:
                        raise UpdateError("Expanded release exceeds manifest size limits")
                    raw.write(chunk)
            raw.seek(0)
            with tarfile.open(fileobj=raw, mode="r:") as source:
                for member in source:
                    name = member.name
                    if (
                        not member.isfile()
                        or name not in manifest.files
                        or name in seen
                        or member.size != manifest.files[name].size
                        or not permitted(name)
                    ):
                        raise UpdateError("Invalid release archive structure")
                    seen.add(name)
                    output = target / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    stream = source.extractfile(member)
                    if stream is None:
                        raise UpdateError("Unreadable release member")
                    with stream, output.open("xb") as dest:
                        shutil.copyfileobj(stream, dest)
                    os.chmod(output, 0o644)
                    if sha256(output) != manifest.files[name].sha256:
                        raise UpdateError("Release file checksum mismatch")
        if seen != set(manifest.files):
            raise UpdateError("Release is missing required files")
        version = tomllib.loads((target / "server/pyproject.toml").read_text("utf-8"))["project"][
            "version"
        ]
        if version != manifest.version:
            raise UpdateError("Manifest version does not match canonical application version")
        if migration_head(target) != manifest.migration_revision:
            raise UpdateError("Manifest does not match packaged migration head")
        for required in (
            "server/Dockerfile",
            "server/app/main.py",
            "frontend/Dockerfile.production",
            "frontend/package-lock.json",
            "frontend/nginx.conf",
        ):
            if required not in seen:
                raise UpdateError("Release is incomplete")
    except (OSError, EOFError, KeyError, tarfile.TarError, SyntaxError, ValueError):
        raise UpdateError("Release archive is corrupt or incompatible") from None


def migration_head(root: Path) -> str:
    revisions: dict[str, str | None] = {}
    for path in (root / "server/alembic/versions").glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text("utf-8")).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for name in targets:
                    if isinstance(name, ast.Name) and name.id in {"revision", "down_revision"}:
                        values[name.id] = ast.literal_eval(node.value)
        if values.get("revision"):
            if not isinstance(values["revision"], str) or not isinstance(
                values.get("down_revision"), (str, type(None))
            ):
                raise UpdateError("Release must use a linear string migration chain")
            if values["revision"] in revisions:
                raise UpdateError("Duplicate migration revision")
            revisions[values["revision"]] = values["down_revision"]
    heads = set(revisions) - set(revisions.values())
    if len(heads) != 1:
        raise UpdateError("Release must have one migration head")
    head = heads.pop()
    visited = set()
    current = head
    while current is not None:
        if current in visited or current not in revisions:
            raise UpdateError("Release has an invalid migration chain")
        visited.add(current)
        current = revisions[current]
    if len(visited) != len(revisions):
        raise UpdateError("Release has disconnected migrations")
    return head
