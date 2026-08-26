"""Preview and explicit approval for Garmin workout publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from swim_coach.application.ports.repositories import UnitOfWork, UnitOfWorkFactory
from swim_coach.application.services.garmin_workout_compiler import GarminWorkoutCompiler
from swim_coach.domain.actions import (
    ActionApproval,
    ActionDecision,
    ActionExecution,
    ActionProposal,
    ExternalWorkoutBinding,
)
from swim_coach.domain.operations import AuditEvent, Job, OutboxEvent
from swim_coach.domain.shared.errors import (
    DomainError,
    ResourceNotFoundError,
    RevisionConflictError,
)
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import PlannedWorkout, WorkoutRevision, WorkoutSchedule


@dataclass(frozen=True, slots=True)
class GarminActionDetail:
    proposal: ActionProposal
    execution: ActionExecution | None


class GarminPublishService:
    ACTION_TYPE = "garmin.publish_and_schedule.v1"
    PUBLISH_JOB_TYPE = "workout.publish_garmin"

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        write_enabled: bool = False,
        allow_fake_device: bool = False,
        canary_title_prefix: str | None = None,
        proposal_ttl: timedelta = timedelta(minutes=15),
        compiler: GarminWorkoutCompiler | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._write_enabled = write_enabled
        self._allow_fake_device = allow_fake_device
        self._canary_title_prefix = canary_title_prefix
        self._proposal_ttl = proposal_ttl
        self._compiler = compiler or GarminWorkoutCompiler()

    @property
    def write_enabled(self) -> bool:
        return self._write_enabled

    async def preview(
        self,
        user_id: UserId,
        workout_id: EntityId,
        *,
        expected_workout_version: int,
        device_id: EntityId | None,
        correlation_id: CorrelationId,
    ) -> GarminActionDetail:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            workout, revision, schedule = await self._publication_input(
                uow, user_id, workout_id, expected_workout_version=expected_workout_version
            )
            devices = [
                device for device in await uow.devices.list(user_id) if device.provider == "garmin"
            ]
            selected = next(
                (device for device in devices if device_id is not None and device.id == device_id),
                None,
            )
            if device_id is not None and selected is None:
                raise ResourceNotFoundError("device")
            selected = selected or next((device for device in devices if device.is_primary), None)
            selected = selected or (devices[0] if devices else None)
            if selected is None and not self._allow_fake_device:
                raise DomainError(
                    "GARMIN_DEVICE_REQUIRED", "Import Garmin devices before publishing a workout."
                )
            selected_id = (
                selected.id if selected else EntityId.parse("00000000-0000-0000-0000-000000000707")
            )
            external_device_id = selected.external_device_id if selected else "fake-device-p07"
            device_name = selected.name if selected else "Relógio simulado"
            device_model = selected.model if selected else "Garmin fake local"
            compiled = self._compiler.compile(revision)
            binding = await uow.external_workout_bindings.get_by_revision_hash(
                user_id, "garmin", revision.id, compiled.compiled_hash
            )
            self._assert_revision_unbound(binding)
            payload = cast(
                JsonObject,
                {
                    "provider": "garmin",
                    "workout_id": str(workout.id),
                    "revision_id": str(revision.id),
                    "revision_content_hash": revision.content_hash,
                    "source_revision_hash": compiled.source_revision_hash,
                    "compiled_hash": compiled.compiled_hash,
                    "compiled_payload": compiled.payload,
                    "scheduled_date": schedule.scheduled_date.isoformat(),
                    "device_id": str(selected_id),
                    "external_device_id": external_device_id,
                },
            )
            impact = cast(
                JsonObject,
                {
                    "title": workout.title,
                    "distance_m": revision.totals.distance_m,
                    "scheduled_date": schedule.scheduled_date.isoformat(),
                    "device": {
                        "id": str(selected_id),
                        "name": device_name,
                        "model": device_model,
                    },
                    "external_effects": ["create Garmin workout", "add to Garmin calendar"],
                    "warnings": list(compiled.warnings),
                },
            )
            proposal = ActionProposal.ready_for_review(
                id=EntityId.new(),
                user_id=user_id,
                action_type=self.ACTION_TYPE,
                target_type="planned_workout",
                target_id=workout.id,
                target_revision_id=revision.id,
                payload=payload,
                impact=impact,
                expires_at=now + self._proposal_ttl,
                created_at=now,
            )
            existing = await uow.action_proposals.get_by_hash(user_id, proposal.action_hash)
            if existing is not None:
                execution = await uow.action_executions.get_by_proposal(user_id, existing.id)
                return GarminActionDetail(existing, execution)
            await uow.action_proposals.add(proposal)
            await self._record(
                uow,
                proposal,
                correlation_id,
                event_type="swim_coach.actions.garmin_publish_proposed.v1",
                action="actions.garmin_publish_proposed",
            )
            await uow.commit()
            return GarminActionDetail(proposal, None)

    async def get(self, user_id: UserId, proposal_id: EntityId) -> GarminActionDetail:
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get(user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            execution = await uow.action_executions.get_by_proposal(user_id, proposal.id)
            return GarminActionDetail(proposal, execution)

    async def approve(
        self,
        user_id: UserId,
        proposal_id: EntityId,
        *,
        expected_version: int,
        action_hash: str,
        correlation_id: CorrelationId,
        explicit_verb: str | None = None,
    ) -> GarminActionDetail:
        if not self._write_enabled:
            raise DomainError(
                "GARMIN_WRITE_DISABLED",
                "Garmin publication is disabled by the server kill switch.",
            )
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get_for_update(user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            if proposal.version != expected_version:
                raise RevisionConflictError(proposal.version)
            workout, revision, schedule = await self._publication_input(
                uow, user_id, proposal.target_id, expected_workout_version=None
            )
            if self._canary_title_prefix and not workout.title.startswith(
                self._canary_title_prefix
            ):
                raise DomainError(
                    "GARMIN_CANARY_REQUIRED",
                    "Live publication is limited to titles starting with "
                    f"{self._canary_title_prefix}.",
                )
            self._assert_proposal_current(proposal, workout, revision, schedule)
            compiled = self._compiler.compile(revision)
            if compiled.compiled_hash != proposal.payload.get("compiled_hash"):
                raise DomainError("REVISION_CONFLICT", "The compiled workout changed since review.")
            binding = await uow.external_workout_bindings.get_by_revision_hash(
                user_id, "garmin", revision.id, compiled.compiled_hash
            )
            self._assert_revision_unbound(binding)
            previous_version = proposal.version
            proposal.approve(action_hash=action_hash, now=now)
            recorded_verb = (
                explicit_verb.strip()[:200]
                if explicit_verb and explicit_verb.strip()
                else f"Publicar {revision.totals.distance_m:,} m na Garmin"
            )
            approval = ActionApproval(
                id=EntityId.new(),
                proposal_id=proposal.id,
                user_id=user_id,
                action_hash=proposal.action_hash,
                decision=ActionDecision.APPROVE,
                explicit_verb=recorded_verb,
                created_at=now,
            )
            await uow.action_approvals.add(approval)
            await uow.action_proposals.update(proposal, expected_version=previous_version)
            await self._record(
                uow,
                proposal,
                correlation_id,
                event_type="swim_coach.actions.garmin_publish_approved.v1",
                action="actions.garmin_publish_approved",
            )
            await uow.commit()
            return GarminActionDetail(proposal, None)

    async def execute(
        self,
        user_id: UserId,
        proposal_id: EntityId,
        *,
        idempotency_key: str,
        correlation_id: CorrelationId,
    ) -> GarminActionDetail:
        """Queue an already-approved exact proposal in a separate transaction.

        Keeping this boundary separate from :meth:`approve` prevents an MCP client from
        turning a preview response into an external effect in the same tool call.
        """

        if not self._write_enabled:
            raise DomainError(
                "GARMIN_WRITE_DISABLED",
                "Garmin publication is disabled by the server kill switch.",
            )
        if not 8 <= len(idempotency_key.strip()) <= 200:
            raise DomainError(
                "VALIDATION_FAILED", "idempotency_key must contain between 8 and 200 characters."
            )
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get_for_update(user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            existing_execution = await uow.action_executions.get_by_proposal(user_id, proposal.id)
            if existing_execution is not None:
                return GarminActionDetail(proposal, existing_execution)
            workout, revision, schedule = await self._publication_input(
                uow, user_id, proposal.target_id, expected_workout_version=None
            )
            if self._canary_title_prefix and not workout.title.startswith(
                self._canary_title_prefix
            ):
                raise DomainError(
                    "GARMIN_CANARY_REQUIRED",
                    "Live publication is limited to titles starting with "
                    f"{self._canary_title_prefix}.",
                )
            self._assert_proposal_current(proposal, workout, revision, schedule)
            compiled = self._compiler.compile(revision)
            if compiled.compiled_hash != proposal.payload.get("compiled_hash"):
                raise DomainError("REVISION_CONFLICT", "The compiled workout changed since review.")
            previous_version = proposal.version
            proposal.queue(now)
            execution = ActionExecution(
                id=EntityId.new(),
                proposal_id=proposal.id,
                user_id=user_id,
                idempotency_key=self._idempotency_key(proposal, idempotency_key),
                created_at=now,
                updated_at=now,
            )
            binding = await uow.external_workout_bindings.get_by_revision_hash(
                user_id, "garmin", revision.id, compiled.compiled_hash
            )
            self._assert_revision_unbound(binding)
            binding = ExternalWorkoutBinding(
                id=EntityId.new(),
                user_id=user_id,
                workout_id=workout.id,
                revision_id=revision.id,
                provider="garmin",
                compiled_hash=compiled.compiled_hash,
                created_at=now,
                updated_at=now,
            )
            await uow.external_workout_bindings.add(binding)
            job = Job(
                id=EntityId.new(),
                user_id=user_id,
                job_type=self.PUBLISH_JOB_TYPE,
                payload={
                    "proposal_id": str(proposal.id),
                    "execution_id": str(execution.id),
                    "binding_id": str(binding.id),
                },
                idempotency_key=execution.idempotency_key,
                max_attempts=3,
                created_at=now,
                updated_at=now,
                available_at=now,
            )
            await uow.action_executions.add(execution)
            await uow.jobs.add_idempotent(job)
            await uow.action_proposals.update(proposal, expected_version=previous_version)
            await self._record(
                uow,
                proposal,
                correlation_id,
                event_type="swim_coach.actions.garmin_publish_queued.v1",
                action="actions.garmin_publish_queued",
            )
            await uow.commit()
            return GarminActionDetail(proposal, execution)

    async def reject(
        self,
        user_id: UserId,
        proposal_id: EntityId,
        *,
        expected_version: int,
        action_hash: str,
        correlation_id: CorrelationId,
    ) -> GarminActionDetail:
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            proposal = await uow.action_proposals.get_for_update(user_id, proposal_id)
            if proposal is None:
                raise ResourceNotFoundError("action_proposal")
            if proposal.version != expected_version:
                raise RevisionConflictError(proposal.version)
            previous_version = proposal.version
            proposal.reject(action_hash=action_hash, now=now)
            await uow.action_approvals.add(
                ActionApproval(
                    id=EntityId.new(),
                    proposal_id=proposal.id,
                    user_id=user_id,
                    action_hash=proposal.action_hash,
                    decision=ActionDecision.REJECT,
                    explicit_verb="Não publicar na Garmin",
                    created_at=now,
                )
            )
            await uow.action_proposals.update(proposal, expected_version=previous_version)
            await self._record(
                uow,
                proposal,
                correlation_id,
                event_type="swim_coach.actions.garmin_publish_rejected.v1",
                action="actions.garmin_publish_rejected",
            )
            await uow.commit()
            return GarminActionDetail(proposal, None)

    @staticmethod
    async def _publication_input(
        uow: UnitOfWork,
        user_id: UserId,
        workout_id: EntityId,
        *,
        expected_workout_version: int | None,
    ) -> tuple[PlannedWorkout, WorkoutRevision, WorkoutSchedule]:
        workout = await uow.workouts.get(user_id, workout_id)
        if workout is None:
            raise ResourceNotFoundError("workout")
        if expected_workout_version is not None and workout.version != expected_workout_version:
            raise RevisionConflictError(workout.version)
        if (
            workout.current_revision_id is None
            or workout.approved_revision_id != workout.current_revision_id
        ):
            raise DomainError(
                "APPROVAL_REQUIRED", "Approve the current revision before publishing."
            )
        revision = await uow.workout_revisions.get(user_id, workout.current_revision_id)
        schedule = await uow.workout_schedules.get(user_id, workout.id)
        if revision is None or schedule is None:
            raise DomainError(
                "SCHEDULE_REQUIRED", "Schedule the approved workout before publishing."
            )
        return workout, revision, schedule

    @staticmethod
    def _assert_proposal_current(
        proposal: ActionProposal,
        workout: PlannedWorkout,
        revision: WorkoutRevision,
        schedule: WorkoutSchedule,
    ) -> None:
        if revision.id != proposal.target_revision_id or workout.current_revision_id != revision.id:
            raise DomainError("REVISION_CONFLICT", "The workout revision changed since review.")
        if proposal.payload.get("scheduled_date") != schedule.scheduled_date.isoformat():
            raise DomainError("REVISION_CONFLICT", "The workout schedule changed since review.")

    @staticmethod
    def _assert_revision_unbound(binding: ExternalWorkoutBinding | None) -> None:
        if binding is None:
            return
        details: dict[str, str] = {"binding_status": binding.status.value}
        if binding.scheduled_date is not None:
            details["scheduled_date"] = binding.scheduled_date.isoformat()
        raise DomainError(
            "GARMIN_REVISION_ALREADY_BOUND",
            "This exact workout revision already has Garmin publication state. "
            "Use its existing operation instead of publishing it again.",
            details=details,
        )

    @staticmethod
    def _idempotency_key(proposal: ActionProposal, client_key: str) -> str:
        client_digest = hashlib.sha256(client_key.strip().encode()).hexdigest()
        return f"garmin:publish:{proposal.id}:{client_digest}"

    @staticmethod
    async def _record(
        uow: UnitOfWork,
        proposal: ActionProposal,
        correlation_id: CorrelationId,
        *,
        event_type: str,
        action: str,
    ) -> None:
        payload: JsonObject = {
            "proposal_id": str(proposal.id),
            "action_hash": proposal.action_hash,
            "status": proposal.status.value,
            "version": proposal.version,
        }
        await uow.outbox.add(
            OutboxEvent(
                id=EntityId.new(),
                aggregate_type="ActionProposal",
                aggregate_id=proposal.id,
                aggregate_version=proposal.version,
                event_type=event_type,
                payload=payload,
                user_id=proposal.user_id,
                correlation_id=correlation_id,
            )
        )
        await uow.audit.add(
            AuditEvent(
                id=EntityId.new(),
                user_id=proposal.user_id,
                actor_type="user",
                actor_id=str(proposal.user_id),
                action=action,
                entity_type="ActionProposal",
                entity_id=proposal.id,
                correlation_id=correlation_id,
                after=payload,
            )
        )
