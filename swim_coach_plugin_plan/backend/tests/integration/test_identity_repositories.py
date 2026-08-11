from sqlalchemy import func, select

from swim_coach.application.services import IdentityService
from swim_coach.domain.shared import CorrelationId, EntityId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.infrastructure.db.models import AuditEventModel, OutboxEventModel


async def test_identity_bootstrap_is_idempotent_transactional_and_user_scoped(
    database: Database,
) -> None:
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=frozenset({"first@example.test", "second@example.test"}),
        allowed_subjects=frozenset(),
    )
    first = await identity.ensure_identity(
        provider="test-oidc",
        subject="subject-first",
        email="first@example.test",
        display_name="Primeiro",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    repeated = await identity.ensure_identity(
        provider="test-oidc",
        subject="subject-first",
        email="first@example.test",
        display_name="Primeiro",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    second = await identity.ensure_identity(
        provider="test-oidc",
        subject="subject-second",
        email="second@example.test",
        display_name="Segundo",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )

    assert repeated.id == first.id
    async with uow_factory() as uow:
        first_pools = await uow.pools.list(first.id)
        first_goals = await uow.goals.list(first.id)
        assert await uow.pools.get(second.id, first_pools[0].id) is None
        assert await uow.goals.get(second.id, first_goals[0].id) is None

    assert len(first_pools) == 1
    assert first_pools[0].length.meters == 20
    assert first_pools[0].is_default is True
    assert len(first_goals) == 1
    assert first_goals[0].target_distance.meters == 2_000
    assert int(first_goals[0].target_duration.seconds) == 2_700
    assert int(first_goals[0].target_pace.seconds_per_100m) == 135

    async with database.session_factory() as session:
        outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventModel))
        audit_count = await session.scalar(select(func.count()).select_from(AuditEventModel))
    assert outbox_count == 2
    assert audit_count == 3
    assert EntityId(first.id.value) != EntityId(second.id.value)
