"""Encrypted PostgreSQL and artifact backup envelopes with verified restore."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"SCBK1"
NONCE_BYTES = 12
Runner = Callable[[Sequence[str]], None]


def _run(command: Sequence[str]) -> None:
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL)  # noqa: S603


def load_key(path: Path) -> bytes:
    """Load a URL-safe base64 256-bit key from a private file."""

    if path.stat().st_mode & 0o077:
        raise ValueError("backup key file must not be accessible by group or others")
    try:
        key = base64.urlsafe_b64decode(path.read_text().strip())
    except (ValueError, OSError) as exc:
        raise ValueError("backup key file is invalid") from exc
    if len(key) != 32:
        raise ValueError("backup key must contain exactly 32 bytes")
    return key


def create_backup(
    database_url: str,
    artifacts_root: Path,
    destination: Path,
    key: bytes,
    *,
    runner: Runner = _run,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create an atomic encrypted backup and return its non-secret manifest."""

    _validate_key(key)
    artifacts_root = artifacts_root.resolve()
    destination = destination.resolve()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="swim-coach-backup-") as temporary:
        stage = Path(temporary)
        database_dump = stage / "database.dump"
        runner(
            [
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--no-acl",
                "--file",
                str(database_dump),
                database_url,
            ]
        )
        if not database_dump.is_file():
            raise RuntimeError("pg_dump did not produce a backup")
        artifact_entries = _artifact_manifest(artifacts_root)
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "created_at": (now or datetime.now(UTC)).isoformat(),
            "database": {
                "file": "database.dump",
                "size_bytes": database_dump.stat().st_size,
                "sha256": _sha256_file(database_dump),
            },
            "artifacts": artifact_entries,
            "artifact_count": len(artifact_entries),
            "artifact_bytes": sum(int(item["size_bytes"]) for item in artifact_entries),
        }
        bundle = _bundle(database_dump, artifacts_root, manifest)
        nonce = os.urandom(NONCE_BYTES)
        encrypted = MAGIC + nonce + AESGCM(key).encrypt(nonce, bundle, MAGIC)
        temporary_output = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        try:
            temporary_output.write_bytes(encrypted)
            os.chmod(temporary_output, 0o600)
            os.replace(temporary_output, destination)
        finally:
            temporary_output.unlink(missing_ok=True)
    return manifest


def restore_backup(
    source: Path,
    database_url: str,
    artifacts_root: Path,
    key: bytes,
    *,
    runner: Runner = _run,
    allow_nonempty_artifacts: bool = False,
) -> dict[str, Any]:
    """Verify and restore into an explicitly isolated database/storage target."""

    _validate_key(key)
    artifacts_root = artifacts_root.resolve()
    if artifacts_root.exists() and any(artifacts_root.iterdir()) and not allow_nonempty_artifacts:
        raise ValueError("restore artifact target must be empty")
    with tempfile.TemporaryDirectory(prefix="swim-coach-restore-") as temporary:
        stage = Path(temporary)
        manifest = _decrypt_and_extract(source.resolve(), key, stage)
        runner(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--dbname",
                database_url,
                str(stage / "database.dump"),
            ]
        )
        restored_artifacts = stage / "artifacts"
        artifacts_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if restored_artifacts.exists():
            for source_file in restored_artifacts.rglob("*"):
                if not source_file.is_file():
                    continue
                relative = source_file.relative_to(restored_artifacts)
                target = artifacts_root / relative
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copyfile(source_file, target)
                os.chmod(target, 0o600)
    return manifest


def prune_backups(directory: Path, *, retain: int, protected: Path | None = None) -> list[Path]:
    """Apply count-based retention to encrypted backup envelopes only."""

    if retain < 1:
        raise ValueError("at least one encrypted backup must be retained")
    protected_path = protected.resolve() if protected is not None else None
    candidates = sorted(
        (path for path in directory.resolve().glob("*.scbk") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed: list[Path] = []
    retained = 0
    for path in candidates:
        if path.resolve() == protected_path or retained < retain:
            retained += 1
            continue
        path.unlink()
        removed.append(path)
    return removed


def _bundle(database_dump: Path, artifacts_root: Path, manifest: dict[str, Any]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        archive.add(database_dump, arcname="database.dump", recursive=False)
        encoded_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(encoded_manifest)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(encoded_manifest))
        if artifacts_root.is_dir():
            for item in manifest["artifacts"]:
                relative = Path(cast(str, item["path"]))
                archive.add(
                    artifacts_root / relative,
                    arcname=str(Path("artifacts") / relative),
                    recursive=False,
                )
    return stream.getvalue()


def _decrypt_and_extract(source: Path, key: bytes, target: Path) -> dict[str, Any]:
    encrypted = source.read_bytes()
    if len(encrypted) <= len(MAGIC) + NONCE_BYTES or not encrypted.startswith(MAGIC):
        raise ValueError("backup envelope is invalid")
    nonce = encrypted[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
    bundle = AESGCM(key).decrypt(nonce, encrypted[len(MAGIC) + NONCE_BYTES :], MAGIC)
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise ValueError("backup contains an unsafe archive member")
            if path.name not in {"database.dump", "manifest.json"} and path.parts[0] != "artifacts":
                raise ValueError("backup contains an unexpected archive member")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError("backup archive member is unreadable")
            destination = target / path
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.write_bytes(extracted.read())
            os.chmod(destination, 0o600)
    manifest = cast(dict[str, Any], json.loads((target / "manifest.json").read_text()))
    _verify_manifest(target, manifest)
    return manifest


def _verify_manifest(target: Path, manifest: dict[str, Any]) -> None:
    database = cast(dict[str, Any], manifest.get("database"))
    if manifest.get("schema_version") != "1.0" or not isinstance(database, dict):
        raise ValueError("backup manifest schema is unsupported")
    if _sha256_file(target / "database.dump") != database.get("sha256"):
        raise ValueError("database dump checksum mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("backup artifact manifest is invalid")
    for raw_item in artifacts:
        item = cast(dict[str, Any], raw_item)
        relative = Path(cast(str, item["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("backup artifact path is unsafe")
        if _sha256_file(target / "artifacts" / relative) != item.get("sha256"):
            raise ValueError("artifact checksum mismatch")


def _artifact_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("artifact backup refuses symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        result.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_key(key: bytes) -> None:
    if len(key) != 32:
        raise ValueError("backup key must contain exactly 32 bytes")
