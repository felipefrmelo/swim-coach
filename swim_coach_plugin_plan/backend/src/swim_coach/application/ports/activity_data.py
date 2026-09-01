"""Ports for FIT decoding and immutable activity artifact storage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from swim_coach.domain.activities import NormalizedActivity
from swim_coach.domain.shared.value_objects import EntityId, UserId


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    content_type: str
    size_bytes: int
    checksum: str


class ObjectStorage(Protocol):
    async def put_atomic(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        checksum: str,
    ) -> StoredObject: ...

    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str, *, checksum: str | None = None) -> bool: ...
    async def delete(self, key: str) -> None: ...
    async def readiness(self) -> bool: ...


class FitActivityParser(Protocol):
    @property
    def parser_version(self) -> str: ...

    @property
    def profile_version(self) -> str: ...

    def normalize(
        self,
        data: bytes,
        *,
        user_id: UserId,
        activity_id: EntityId,
        artifact_id: EntityId,
        input_checksum: str,
        fallback_pool_length_m: int | None,
    ) -> NormalizedActivity: ...
