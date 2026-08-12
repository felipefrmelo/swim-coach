"""Async PostgreSQL engine lifecycle."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from swim_coach.domain.shared.errors import DomainError


def async_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError("only PostgreSQL database URLs are supported")


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            async_database_url(url),
            echo=echo,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def ping(self) -> bool:
        async with self.engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            value: int = result.scalar_one()
            return value == 1

    async def revision(self) -> str:
        async with self.engine.connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            return str(result.scalar_one())

    @asynccontextmanager
    async def user_advisory_lock(self, user_scope: str) -> AsyncIterator[None]:
        """Serialize provider work for one user across all worker processes."""

        digest = hashlib.blake2b(user_scope.encode(), digest_size=8).digest()
        lock_key = int.from_bytes(digest, byteorder="big", signed=True)
        async with self.engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
            )
            if acquired is not True:
                raise DomainError(
                    "JOB_ALREADY_RUNNING",
                    "A user-scoped operation is already running.",
                )
            try:
                yield
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})

    async def dispose(self) -> None:
        await self.engine.dispose()
