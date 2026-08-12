"""Atomic, checksum-verified filesystem storage rooted in a private directory."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from swim_coach.application.ports.activity_data import StoredObject
from swim_coach.domain.shared.errors import DomainError


class FilesystemObjectStorage:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise DomainError("STORAGE_KEY_INVALID", "Artifact storage key is invalid.")
        target = (self._root / key).resolve()
        if not target.is_relative_to(self._root):
            raise DomainError("STORAGE_KEY_INVALID", "Artifact storage key is invalid.")
        return target

    async def put_atomic(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum: str,
    ) -> StoredObject:
        return self._put_atomic(key, data, content_type=content_type, checksum=checksum)

    def _put_atomic(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum: str,
    ) -> StoredObject:
        actual_checksum = hashlib.sha256(data).hexdigest()
        if actual_checksum != checksum:
            raise DomainError("ARTIFACT_CHECKSUM_MISMATCH", "Artifact checksum did not match.")
        target = self._path(key)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        if target.exists():
            existing = target.read_bytes()
            if hashlib.sha256(existing).hexdigest() != checksum:
                raise DomainError("ARTIFACT_CHECKSUM_CONFLICT", "Stored artifact differs.")
        else:
            temporary_name: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                    temporary_name = temporary.name
                    os.chmod(temporary_name, 0o600)
                    temporary.write(data)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_name, target)
                temporary_name = None
            finally:
                if temporary_name is not None:
                    Path(temporary_name).unlink(missing_ok=True)
        return StoredObject(key, content_type, len(data), checksum)

    async def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise DomainError(
                "FIT_FILE_UNAVAILABLE", "Activity FIT artifact is unavailable."
            ) from exc

    async def exists(self, key: str, *, checksum: str | None = None) -> bool:
        path = self._path(key)
        if not path.is_file():
            return False
        if checksum is None:
            return True
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest() == checksum
