import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError

from swim_coach.application.services import ActivityDataService, GarminSyncService, IdentityService
from swim_coach.application.services.activity_views import activity_detail_v2
from swim_coach.domain.activities.checkin import SwimCheckIn
from swim_coach.domain.shared import CorrelationId, UserId
from swim_coach.domain.shared.errors import DomainError
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.storage import FilesystemObjectStorage

from .test_activity_data import FixtureParser
from .test_garmin_sync import FixtureGarminProvider, no_op_user_lock

ROOT = Path(__file__).resolve().parents[3]


async def test_checkin_database_roundtrip_idempotency_and_ownership(
    database: Database,
    tmp_path: Path,
    postgres_database: tuple,
) -> None:
    factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        factory, allowed_emails=frozenset({"first@example.test"}), allowed_subjects=frozenset()
    )
    owner = await identity.ensure_identity(
        provider="test",
        subject="checkin-owner",
        email="first@example.test",
        display_name="Synthetic swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    provider = FixtureGarminProvider()
    sync = GarminSyncService(factory, provider, no_op_user_lock, lookback_days=365, page_size=1)
    await sync.sync(owner.id, trigger="test")
    async with factory() as uow:
        activities = await uow.activities.list_recent(owner.id)
    activity = activities[0]
    recorded_distance = activity.distance.meters
    service = ActivityDataService(
        factory, provider, FilesystemObjectStorage(tmp_path), FixtureParser()
    )
    kwargs = dict(
        rpe=None,
        technique_rating=None,
        fatigue_rating=None,
        enjoyment_rating=None,
        pain_present=False,
        pain_location=None,
        pain_intensity=None,
        comment=None,
        expected_version=None,
        actor_id="fixture",
        correlation_id=CorrelationId.new(),
        check_in=SwimCheckIn(completed_as_planned=True, watch_data_accurate=False),
        check_in_only=True,
        idempotency_key="checkin-fixture",
        request_hash="a" * 64,
    )
    first = await service.record_feedback(owner.id, activity.id, **kwargs)
    replay = await service.record_feedback(owner.id, activity.id, **kwargs)
    assert first is not None and replay is not None
    assert replay.id == first.id and replay.version == first.version
    async with factory() as uow:
        loaded = await uow.activity_data.get_feedback(owner.id, activity.id)
    assert loaded is not None
    assert loaded.check_in == kwargs["check_in"]
    assert loaded.rpe is None
    view = activity_detail_v2(await service.get(owner.id, activity.id))
    assert view["distance_m"] == recorded_distance
    assert view["execution_evidence"]["completion"] == "CONFIRMED_COMPLETE"
    assert view["execution_evidence"]["performance_blocked"] is True
    with pytest.raises(DomainError):
        await service.record_feedback(UserId.new(), activity.id, **kwargs)
    with pytest.raises(DomainError, match="idempotency"):
        await service.record_feedback(owner.id, activity.id, **{**kwargs, "request_hash": "b" * 64})
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.attributes["database_url"] = postgres_database[0]
    with pytest.raises(DBAPIError, match="would discard athlete check-ins"):
        await asyncio.to_thread(command.downgrade, config, "000015")
    assert await database.revision() == "000016"
    async with factory() as uow:
        protected = await uow.activity_data.get_feedback(owner.id, activity.id)
    assert protected is not None and protected.check_in == loaded.check_in
