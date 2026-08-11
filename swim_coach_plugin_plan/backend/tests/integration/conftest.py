from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from testcontainers.community.postgres import PostgresContainer

from swim_coach.infrastructure.db import Database
from swim_coach.settings import Settings

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class MigrationRoundTrip:
    tables_after_upgrade: frozenset[str]
    tables_after_downgrade: frozenset[str]


async def _table_names(database_url: str) -> frozenset[str]:
    database = Database(database_url)
    try:
        async with database.engine.connect() as connection:
            names = await connection.run_sync(
                lambda sync_connection: inspect(sync_connection).get_table_names()
            )
        return frozenset(names)
    finally:
        await database.dispose()


@pytest.fixture(scope="session")
def postgres_database() -> Iterator[tuple[str, MigrationRoundTrip]]:
    with PostgresContainer(
        image="postgres:16.10-alpine",
        username="swim_coach_test",
        password="local_test_only",  # noqa: S106 - disposable Testcontainer credential
        dbname="swim_coach_test",
        driver="asyncpg",
    ) as postgres:
        database_url = postgres.get_connection_url(driver="asyncpg")
        config = Config(str(ROOT / "backend/alembic.ini"))
        config.attributes["database_url"] = database_url
        command.upgrade(config, "head")
        tables_after_upgrade = asyncio.run(_table_names(database_url))
        command.downgrade(config, "base")
        tables_after_downgrade = asyncio.run(_table_names(database_url))
        command.upgrade(config, "head")
        yield database_url, MigrationRoundTrip(tables_after_upgrade, tables_after_downgrade)


@pytest_asyncio.fixture
async def database(postgres_database: tuple[str, MigrationRoundTrip]) -> AsyncIterator[Database]:
    database_url, _ = postgres_database
    database = Database(database_url)
    try:
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE app_user, api_idempotency_record, oidc_login_attempt "
                    "RESTART IDENTITY CASCADE"
                )
            )
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def app_settings(postgres_database: tuple[str, MigrationRoundTrip]) -> Settings:
    database_url, _ = postgres_database
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        pwa_base_url="http://127.0.0.1:14173",
        auth_allowed_emails="first@example.test,second@example.test",
        dev_auth_enabled=True,
        dev_auth_email="first@example.test",
    )
