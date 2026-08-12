import hashlib
from pathlib import Path

import pytest

from swim_coach.domain.shared.errors import DomainError
from swim_coach.infrastructure.storage import FilesystemObjectStorage


@pytest.mark.asyncio
async def test_filesystem_storage_is_atomic_deduplicated_and_checksum_verified(
    tmp_path: Path,
) -> None:
    storage = FilesystemObjectStorage(tmp_path / "artifacts")
    data = b"synthetic-fit"
    checksum = hashlib.sha256(data).hexdigest()
    first = await storage.put_atomic(
        "garmin/user/activity/hash.fit",
        data,
        content_type="application/vnd.ant.fit",
        checksum=checksum,
    )
    second = await storage.put_atomic(
        "garmin/user/activity/hash.fit",
        data,
        content_type="application/vnd.ant.fit",
        checksum=checksum,
    )
    assert first == second
    assert await storage.get(first.key) == data
    assert await storage.exists(first.key, checksum=checksum)
    assert (tmp_path / "artifacts").stat().st_mode & 0o777 == 0o700

    with pytest.raises(DomainError) as error:
        await storage.put_atomic(
            "garmin/user/activity/wrong.fit",
            data,
            content_type="application/vnd.ant.fit",
            checksum="0" * 64,
        )
    assert error.value.code == "ARTIFACT_CHECKSUM_MISMATCH"


@pytest.mark.asyncio
async def test_filesystem_storage_rejects_path_traversal(tmp_path: Path) -> None:
    storage = FilesystemObjectStorage(tmp_path / "artifacts")
    with pytest.raises(DomainError) as error:
        await storage.get("../secret")
    assert error.value.code == "STORAGE_KEY_INVALID"
