"""Developer-only deterministic payload selection from Git-tracked application files."""

import argparse
import os
import subprocess
import tarfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.backup import FileDigest
from app.updates.artifact import migration_head, permitted, sha256
from app.updates.schema import ReleaseManifest, semver


def build(root: Path, output: Path, minimum_version: str, files: list[str]) -> ReleaseManifest:
    root = root.resolve()
    version = tomllib.loads((root / "server/pyproject.toml").read_text("utf-8"))["project"][
        "version"
    ]
    if semver(minimum_version) > semver(version):
        raise ValueError("Minimum version cannot exceed release version")
    selected = {}
    for name in sorted(files):
        path = root / name
        if not permitted(name) or path.is_symlink() or root not in path.resolve().parents:
            raise ValueError("Release contains a forbidden file")
        selected[name] = FileDigest(size=path.stat().st_size, sha256=sha256(path))
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"modbus-monitor-{version}.tar.gz"
    if archive.exists():
        raise ValueError("Refusing to overwrite an existing release artifact")
    with tarfile.open(archive, "w:gz") as tar:
        for name in selected:
            path = root / name
            member = tarfile.TarInfo(name)
            member.size, member.mode = path.stat().st_size, 0o644
            with path.open("rb") as stream:
                tar.addfile(member, stream)
    manifest = ReleaseManifest(
        format="modbus-monitor-release",
        format_version=1,
        version=version,
        minimum_version=minimum_version,
        created_at=datetime.now(UTC),
        migration_revision=migration_head(root),
        sha256=sha256(archive),
        size=archive.stat().st_size,
        files=selected,
    )
    (output / f"modbus-monitor-{version}.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a versioned release from a clean, reviewed Git checkout"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-version", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
    if dirty.strip():
        raise SystemExit("Release creation requires a clean reviewed checkout")
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "server", "frontend"],
            cwd=root,
        )
        .decode("utf-8")
        .split("\0")
    )
    manifest = build(root, args.output, args.minimum_version, [name for name in tracked if name])
    os.chmod(args.output / f"modbus-monitor-{manifest.version}.json", 0o644)
    print(f"Created release {manifest.version}; publish the .tar.gz and .json together")


if __name__ == "__main__":
    main()
