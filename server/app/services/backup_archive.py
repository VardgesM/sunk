"""Bounded, authenticated encryption and strict archive validation. No SQL execution."""

import hashlib
import os
import shutil
import tarfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from pydantic import ValidationError

from app.schemas.backup import FileDigest, Manifest

MAGIC = b"MMBACKUP\x01"
CHUNK = 1024 * 1024
MEMBERS = {"manifest.json", "database.dump", "configuration/settings.json"}


class BackupError(ValueError):
    """Only deliberately sanitized messages may cross the API boundary."""


def digest_file(path: Path) -> FileDigest:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return FileDigest(size=path.stat().st_size, sha256=digest.hexdigest())


def key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8"))


def encrypt(source: Path, destination: Path, password: str) -> None:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    cipher = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(header)
    with source.open("rb") as src, destination.open("xb") as dst:
        os.chmod(destination, 0o600)
        dst.write(header)
        while block := src.read(CHUNK):
            dst.write(cipher.update(block))
        dst.write(cipher.finalize())
        dst.write(cipher.tag)


def decrypt(source: Path, destination: Path, password: str, maximum: int) -> None:
    length = source.stat().st_size
    header_size = len(MAGIC) + 28
    if length < header_size + 16 or length > maximum:
        raise BackupError("Invalid backup size")
    with source.open("rb") as src, destination.open("xb") as dst:
        os.chmod(destination, 0o600)
        header = src.read(header_size)
        if not header.startswith(MAGIC):
            raise BackupError("Unsupported encrypted backup format")
        src.seek(-16, os.SEEK_END)
        tag = src.read(16)
        src.seek(header_size)
        cipher = Cipher(
            algorithms.AES(key(password, header[len(MAGIC) :][:16])), modes.GCM(header[-12:], tag)
        ).decryptor()
        cipher.authenticate_additional_data(header)
        remaining = length - header_size - 16
        while remaining:
            block = src.read(min(CHUNK, remaining))
            if not block:
                raise BackupError("Truncated backup")
            remaining -= len(block)
            dst.write(cipher.update(block))
        try:
            dst.write(cipher.finalize())
        except InvalidTag:
            raise BackupError("Incorrect passphrase or damaged backup") from None


def unpack(
    source: Path, destination: Path, password: str, maximum: int, expanded_maximum: int
) -> Manifest:
    archive = destination / "payload.tar.gz"
    decrypt(source, archive, password, maximum)
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for item in tar:
                if item.name not in MEMBERS or item.name in seen or not item.isfile():
                    raise BackupError("Invalid archive structure, duplicate member or unsafe path")
                seen.add(item.name)
                total += item.size
                cap = expanded_maximum if item.name == "database.dump" else 256 * 1024
                if item.size > cap or total > expanded_maximum:
                    raise BackupError("Expanded backup exceeds configured size limit")
                # Only fixed allowlisted basenames; never extract user-controlled paths.
                target = destination / Path(item.name).name
                stream = tar.extractfile(item)
                if stream is None:
                    raise BackupError("Archive member is unreadable")
                with stream, target.open("xb") as output:
                    os.chmod(target, 0o600)
                    shutil.copyfileobj(stream, output, CHUNK)
        if seen != MEMBERS:
            raise BackupError("Backup is missing required files")
        manifest = Manifest.model_validate_json((destination / "manifest.json").read_bytes())
        if set(manifest.files) != MEMBERS - {"manifest.json"}:
            raise BackupError("Manifest has an invalid file list")
        for name, expected in manifest.files.items():
            if digest_file(destination / Path(name).name) != expected:
                raise BackupError("Backup checksum mismatch")
        return manifest
    except (tarfile.TarError, OSError, EOFError, ValidationError):
        raise BackupError("Corrupted archive or unsupported manifest") from None
