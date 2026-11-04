"""Synthetic journeys for successor cycles, calendar repair and external confirmation."""

import asyncio
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from swim_coach.application.ports.garmin import GarminErrorCategory, GarminProviderError
from swim_coach.application.services.context import AvailabilityInput
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.planning import PlanStatus, TrainingPlanDocument
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.domain.workouts.calendar import CalendarRequest
from swim_coach.infrastructure.db.models import ExternalWorkoutBindingModel, JobModel
from swim_coach.infrastructure.garmin import FakeGarminWorkoutProvider
from swim_coach.interfaces.worker.main import Worker

from .test_chatgpt_first_v2 import coach_plan_definition, plan_workout

ROOT = Path(__file__).resolve().parents[3]


async def setup_coach(database, settings):
    services = build_services(
        settings.model_copy(
            update={
                "planning_enabled": True,
                "garmin_write_enabled": True,
                "garmin_write_mode": "fake",
                "mcp_write_enabled": True,
                "mcp_v2_enabled": True,
            }
        ),
        database,
    )
    identity = await services.identity.ensure_identity(
        provider="oidc",
        subject="lifecycle-owner",
        email="first@example.test",
        display_name="Synthetic swimmer",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    uid = identity.id
    pools = await services.context.list_pools(uid)
    pool = pools[0]
    await services.context.replace_availability(
        uid,
        [
            AvailabilityInput(
                day_of_week=d,
                start_local_time=time(6, 15),
                end_local_time=time(7),
                max_duration_minutes=45,
                pool_id=pool.id,
            )
            for d in (1, 3)
        ],
        correlation_id=CorrelationId.new(),
    )
    return services, uid, pool


async def apply(services, uid, proposal):
    return await services.coach_commands.apply_plan_revision(
        uid,
        actor_id="synthetic",
        plan_id=proposal.plan.id,
        proposal_id=proposal.proposal.id,
        expected_revision=0,
        approval_hash=proposal.proposal.action_hash,
        correlation_id=CorrelationId.new(),
    )


@pytest.mark.parametrize("paused", [False, True])
async def test_ended_or_paused_cycle_rolls_over_after_exact_approval(
    database, app_settings, paused
):
    services, uid, pool = await setup_coach(database, app_settings)
    goal = (await services.context.list_goals(uid))[0]
    definition = TrainingPlanDocument.model_validate(
        coach_plan_definition(goal_id=goal.id, start_date=date(2026, 9, 7), pool_id=pool.id)
    )
    first = await services.coach_commands.propose_training_plan(
        uid, actor_id="synthetic", definition=definition, correlation_id=CorrelationId.new()
    )
    await apply(services, uid, first)
    if paused:
        await services.coach_commands.set_training_plan_status(
            uid,
            actor_id="synthetic",
            plan_id=first.plan.id,
            status=PlanStatus.PAUSED,
            correlation_id=CorrelationId.new(),
        )
    previous = await services.coach_commands.get_training_plan(uid, first.plan.id)
    original = previous.revision.document.as_json()
    assert previous.plan.lifecycle_state(date(2026, 11, 2)) == "ENDED_NEEDS_REVIEW"
    changed_goal = await services.coach_commands.operations.set_goal(
        uid,
        title="Synthetic 1000 m / 23 min",
        distance_m=1000,
        duration_seconds=1380,
        expected_goal_version=goal.version,
        correlation_id=CorrelationId.new(),
    )
    current = await services.coach_commands.operations.overview(uid)
    assert current["current_goal"]["pace_seconds_per_100m"] == 138
    assert current["cycles"][0]["goal_relationship"] == "PREVIOUS_OR_UNVERIFIED"
    successor = TrainingPlanDocument.model_validate(
        coach_plan_definition(
            goal_id=EntityId.parse(changed_goal["goal_id"]),
            start_date=date(2026, 11, 2),
            pool_id=pool.id,
        )
    )
    with pytest.raises(DomainError) as blocked:
        await services.coach_commands.propose_training_plan(
            uid, actor_id="synthetic", definition=successor, correlation_id=CorrelationId.new()
        )
    assert blocked.value.details["recovery"]["next_tool"] == "propose_training_plan"
    proposed = await services.coach_commands.propose_training_plan(
        uid,
        actor_id="synthetic",
        definition=successor,
        predecessor_plan_id=first.plan.id,
        expected_predecessor_version=previous.plan.version,
        correlation_id=CorrelationId.new(),
    )
    assert (
        await services.coach_commands.get_training_plan(uid, first.plan.id)
    ).plan.status == previous.plan.status
    with pytest.raises(DomainError):
        await services.coach_commands.apply_plan_revision(
            uid,
            actor_id="synthetic",
            plan_id=proposed.plan.id,
            proposal_id=proposed.proposal.id,
            expected_revision=0,
            approval_hash="0" * 64,
            correlation_id=CorrelationId.new(),
        )
    result = await apply(services, uid, proposed)
    assert result.plan.predecessor_plan_id == first.plan.id
    assert result.plan.status is PlanStatus.ACTIVE
    old = await services.coach_commands.get_training_plan(uid, first.plan.id)
    assert old.plan.status is PlanStatus.COMPLETED
    assert old.revision.document.as_json() == original
    assert (await apply(services, uid, proposed)).revision.id == result.revision.id
    async with services.uow_factory() as uow:
        assert all(j.job_type != "workout.upsert_garmin" for j in await uow.jobs.list_recent(uid))


@pytest.mark.parametrize("fail_cleanup", [False, True])
async def test_calendar_preview_and_published_move_keep_identity_and_confirm_remote(
    database, app_settings, monkeypatch, fail_cleanup
):
    services, uid, pool = await setup_coach(database, app_settings)
    operations = services.coach_commands.operations
    preview = await operations.preview(
        uid,
        requests=[
            CalendarRequest(period="TOMORROW"),
            CalendarRequest(period="THIS_WEEK", weekday="THURSDAY"),
        ],
        reference=datetime(2026, 11, 2, 12, tzinfo=UTC),
        timezone="America/Sao_Paulo",
        start=None,
    )
    assert [s["scheduled_date"] for s in preview["sessions"]] == ["2026-11-03", "2026-11-05"]
    assert all(s["max_duration_minutes"] == 45 for s in preview["sessions"])
    saved = await services.coach_commands.save_workout(
        uid,
        CanonicalWorkout.model_validate(plan_workout(1040, "TECHNIQUE")),
        workout_id=None,
        pool_id=pool.id,
        scheduled_date=date(2026, 11, 10),
        scheduled_start_time=time(6, 15),
        change_reason=None,
        correlation_id=CorrelationId.new(),
    )
    # Fake mode permits publishing without a real athlete device.
    await services.coach_commands.publish_workout(
        uid,
        saved.workout.id,
        scheduled_date=None,
        scheduled_start_time=None,
        device_id=None,
        correlation_id=CorrelationId.new(),
    )
    assert (await operations.publication_status(uid, [saved.workout.id]))["items"][0][
        "state"
    ] == "QUEUED"
    writer = services.garmin_writer
    assert isinstance(writer, FakeGarminWorkoutProvider)
    worker = Worker(services.uow_factory, services.garmin_sync, writer, garmin_write_enabled=True)
    assert await worker.run_once()
    assert (await operations.publication_status(uid, [saved.workout.id]))["all_published"]
    latest = await services.workouts.get_workout(uid, saved.workout.id)
    preview = await operations.preview(
        uid,
        requests=[CalendarRequest(period="ABSOLUTE", local_date=date(2026, 11, 3))],
        reference=None,
        timezone=None,
        start=time(6, 15),
        workout_id=saved.workout.id,
    )
    moved = await operations.reschedule(
        uid,
        saved.workout.id,
        request=CalendarRequest(period="ABSOLUTE", local_date=date(2026, 11, 3)),
        start=time(6, 15),
        expected_version=latest.workout.version,
        expected_calendar_hash=preview["calendar_hash"],
        correlation_id=CorrelationId.new(),
    )
    assert moved["state"] == "QUEUED" and not moved["remote_confirmed"]
    original_unschedule = writer.unschedule_workout
    if fail_cleanup:

        async def fail_old_entry_once(user_id, schedule_id):
            monkeypatch.setattr(writer, "unschedule_workout", original_unschedule)
            raise GarminProviderError(GarminErrorCategory.NETWORK, retryable=True)

        monkeypatch.setattr(writer, "unschedule_workout", fail_old_entry_once)
    assert await worker.run_once()
    if fail_cleanup:
        partial = await operations.publication_status(uid, [saved.workout.id])
        assert not partial["all_published"]
        assert partial["items"][0]["state"] == "RETRYING"
        async with database.engine.begin() as connection:
            await connection.execute(
                update(JobModel)
                .where(JobModel.id == EntityId.parse(moved["job_id"]).value)
                .values(available_at=datetime.now(UTC))
            )
        assert await worker.run_once()
    status = await operations.publication_status(uid, [saved.workout.id])
    assert status["all_published"]
    assert status["items"][0]["remote_date"] == "2026-11-03"
    assert writer.unschedule_calls == 1
    assert writer.create_calls == 1
    assert (
        writer.schedule_calls == 2
    )  # Retry reconciles the new entry instead of creating it again.
    after = await services.workouts.get_workout(uid, saved.workout.id)
    assert after.workout.id == saved.workout.id
    assert len(after.revisions) == 2
    async with database.session_factory() as session:
        bindings = list(await session.scalars(select(ExternalWorkoutBindingModel)))
        assert len(bindings) == 1
        assert bindings[0].scheduled_date == date(2026, 11, 3)


async def test_successor_detects_predecessor_version_change_before_application(
    database, app_settings
):
    services, uid, pool = await setup_coach(database, app_settings)
    goal = (await services.context.list_goals(uid))[0]
    first = await services.coach_commands.propose_training_plan(
        uid,
        actor_id="synthetic",
        definition=TrainingPlanDocument.model_validate(
            coach_plan_definition(goal_id=goal.id, start_date=date(2026, 9, 7), pool_id=pool.id)
        ),
        correlation_id=CorrelationId.new(),
    )
    await apply(services, uid, first)
    current = await services.coach_commands.get_training_plan(uid, first.plan.id)
    successor = await services.coach_commands.propose_training_plan(
        uid,
        actor_id="synthetic",
        definition=TrainingPlanDocument.model_validate(
            coach_plan_definition(goal_id=goal.id, start_date=date(2026, 11, 2), pool_id=pool.id)
        ),
        predecessor_plan_id=first.plan.id,
        expected_predecessor_version=current.plan.version,
        correlation_id=CorrelationId.new(),
    )
    await services.coach_commands.set_training_plan_status(
        uid,
        actor_id="synthetic",
        plan_id=first.plan.id,
        status=PlanStatus.PAUSED,
        correlation_id=CorrelationId.new(),
    )
    with pytest.raises(DomainError, match="predecessor changed"):
        await apply(services, uid, successor)


async def test_adopt_exact_adhoc_preserves_identity_and_replays_materialization(
    database, app_settings
):
    services, uid, pool = await setup_coach(database, app_settings)
    goal = (await services.context.list_goals(uid))[0]
    proposed = await services.coach_commands.propose_training_plan(
        uid,
        actor_id="synthetic",
        definition=TrainingPlanDocument.model_validate(
            coach_plan_definition(goal_id=goal.id, start_date=date(2026, 11, 2), pool_id=pool.id)
        ),
        correlation_id=CorrelationId.new(),
    )
    intent = proposed.document.weeks[0].sessions[0]
    saved = await services.coach_commands.save_workout(
        uid,
        intent.workout,
        workout_id=None,
        pool_id=pool.id,
        scheduled_date=intent.scheduled_date,
        scheduled_start_time=intent.scheduled_start_time,
        change_reason=None,
        correlation_id=CorrelationId.new(),
        origin="CONTINGENCY",
    )
    await apply(services, uid, proposed)
    await services.coach_commands.materialize_plan_week(
        uid,
        plan_id=proposed.plan.id,
        expected_revision=1,
        week_number=1,
        correlation_id=CorrelationId.new(),
    )
    await services.coach_commands.operations.associate(
        uid,
        saved.workout.id,
        plan_id=proposed.plan.id,
        session_intent_id=EntityId.parse(intent.session_intent_id),
        expected_revision=1,
        correlation_id=CorrelationId.new(),
    )
    replay = await services.coach_commands.materialize_plan_week(
        uid,
        plan_id=proposed.plan.id,
        expected_revision=1,
        week_number=1,
        correlation_id=CorrelationId.new(),
    )
    assert saved.workout.id in replay.workout_ids
    detail = await services.coach_commands.get_training_plan(uid, proposed.plan.id)
    binding = next(
        b for b in detail.bindings if str(b.session_intent_id) == intent.session_intent_id
    )
    assert binding.workout_id == saved.workout.id
    agenda = (await services.coach_commands.operations.overview(uid))["agenda"]
    assert len(agenda) == 2
    assert all(w["provenance"] == "PLAN_SESSION" for w in agenda)


async def test_schema_rollback_refuses_workout_metadata_unreadable_by_previous_images(
    database, app_settings
):
    services, uid, pool = await setup_coach(database, app_settings)
    await services.coach_commands.save_workout(
        uid,
        CanonicalWorkout.model_validate(plan_workout(1000, "BASE")),
        workout_id=None,
        pool_id=pool.id,
        scheduled_date=None,
        scheduled_start_time=None,
        change_reason=None,
        correlation_id=CorrelationId.new(),
    )
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.attributes["database_url"] = str(app_settings.database_url)
    with pytest.raises(RuntimeError, match="Lifecycle data exists"):
        await asyncio.to_thread(command.downgrade, config, "000017")
    assert await database.revision() == "000019"


async def test_manual_plan_edit_stages_then_preserves_history_on_exact_approval(
    database, app_settings
):
    from datetime import timedelta

    from swim_coach.domain.planning import TrainingPlanRevisionDefinition

    services, uid, pool = await setup_coach(database, app_settings)
    goal = (await services.context.list_goals(uid))[0]
    today = date.today()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 + 7)
    first = await services.coach_commands.propose_training_plan(
        uid,
        actor_id="synthetic",
        correlation_id=CorrelationId.new(),
        definition=TrainingPlanDocument.model_validate(
            coach_plan_definition(goal_id=goal.id, start_date=monday, pool_id=pool.id)
        ),
    )
    await apply(services, uid, first)
    current = await services.coach_commands.get_training_plan(uid, first.plan.id)
    original = current.revision.document.as_json()
    definition = current.revision.document.as_json()
    definition["weeks"][0]["sessions"][0]["coach_notes"] = "Explicit manual edit"
    proposed = await services.coach_commands.propose_plan_revision(
        uid,
        actor_id="synthetic",
        plan_id=first.plan.id,
        expected_revision=current.plan.current_revision,
        revision_definition=TrainingPlanRevisionDefinition(
            kind="MANUAL_EDIT", rationale="Athlete edit", definition=definition
        ),
        correlation_id=CorrelationId.new(),
    )
    assert (
        await services.coach_commands.get_training_plan(uid, first.plan.id)
    ).revision.document.as_json() == original
    await services.coach_commands.apply_plan_revision(
        uid,
        actor_id="synthetic",
        plan_id=first.plan.id,
        proposal_id=proposed.proposal.id,
        expected_revision=current.plan.current_revision,
        approval_hash=proposed.proposal.action_hash,
        correlation_id=CorrelationId.new(),
    )
    edited = await services.coach_commands.get_training_plan(uid, first.plan.id)
    assert edited.plan.current_revision == current.plan.current_revision + 1
    assert edited.revision.revision_kind.value == "MANUAL_EDIT"
    assert edited.revisions[0].document.as_json() == original
    async with services.uow_factory() as uow:
        assert all(j.job_type != "workout.upsert_garmin" for j in await uow.jobs.list_recent(uid))
