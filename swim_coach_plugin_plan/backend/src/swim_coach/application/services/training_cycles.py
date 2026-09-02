"""Application workflows for approval-gated rolling training cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid5
from zoneinfo import ZoneInfo

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.training_plan_validator import (
    TrainingPlanValidationContext,
    TrainingPlanValidator,
)
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.domain.actions import ActionApproval, ActionDecision, ActionProposal
from swim_coach.domain.goals import GoalStatus
from swim_coach.domain.operations import AuditEvent, Job, OutboxEvent
from swim_coach.domain.planning import (
    EvidenceConfidence,
    NoteAuthor,
    NoteCategory,
    NoteImportance,
    NoteScope,
    PlanDecision,
    PlanDetailLevel,
    PlanNote,
    PlanReview,
    PlanRevisionKind,
    PlanSessionBinding,
    PlanSessionIntent,
    PlanSessionState,
    PlanStatus,
    PlanWeek,
    PrescriptionSource,
    TrainingPlan,
    TrainingPlanDocument,
    TrainingPlanRevision,
    TrainingPlanRevisionDefinition,
    canonical_json_hash,
    plan_document_diff,
)
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    PlannedWorkoutStatus,
    canonical_content_hash,
)


@dataclass(frozen=True, slots=True)
class PlanProposalResult:
    plan: TrainingPlan
    proposal: ActionProposal
    document: TrainingPlanDocument


@dataclass(frozen=True, slots=True)
class PlanDetail:
    plan: TrainingPlan
    revision: TrainingPlanRevision | None
    revisions: tuple[TrainingPlanRevision, ...]
    bindings: tuple[PlanSessionBinding, ...]
    reviews: tuple[PlanReview, ...]
    notes: tuple[PlanNote, ...]


@dataclass(frozen=True, slots=True)
class AppliedPlanRevision:
    plan: TrainingPlan
    revision: TrainingPlanRevision
    materialization_job_ids: tuple[EntityId, ...] = ()
    superseded_session_ids: tuple[EntityId, ...] = ()
    locally_unscheduled_workout_ids: tuple[EntityId, ...] = ()

    @property
    def materialization_job_id(self) -> EntityId | None:
        return self.materialization_job_ids[0] if self.materialization_job_ids else None


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    plan_id: EntityId
    revision: int
    week_number: int
    workout_ids: tuple[EntityId, ...]
    skipped_session_ids: tuple[EntityId, ...]
    replayed: bool


class TrainingCycleService:
    ACTION_TYPE = "training_plan.revision.v1"
    MATERIALIZE_JOB_TYPE = "planning.materialize_cycle_week"

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        workouts: WorkoutService,
        validator: TrainingPlanValidator | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._workouts = workouts
        self._validator = validator or TrainingPlanValidator()

    async def propose_plan(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        definition: TrainingPlanDocument,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        if definition.schema_version != "2.0":
            raise DomainError(
                "LEGACY_RULESET_READ_ONLY",
                "New training plans require a coach-defined schema 2.0 definition.",
            )
        if definition.goal_id is None or definition.start_date is None or definition.title is None:
            raise DomainError("PLAN_VALIDATION_FAILED", "The plan definition is incomplete.")
        goal_id = EntityId.parse(definition.goal_id)
        async with self._uow_factory() as uow:
            if await uow.training_plans.get_live(user_id) is not None:
                raise DomainError(
                    "ACTIVE_PLAN_EXISTS",
                    "Pause, complete, or cancel the current plan before starting another cycle.",
                )
            goals = await uow.goals.list(user_id)
            selected_goal = next((item for item in goals if item.id == goal_id), None)
            user = await uow.users.get(user_id)
            pools = tuple(await uow.pools.list(user_id))
            availability = tuple(await uow.availability.list(user_id))
        if selected_goal is None or selected_goal.status is not GoalStatus.ACTIVE:
            raise DomainError("GOAL_REQUIRED", "Choose an active goal before creating a plan.")
        if user is None:
            raise ResourceNotFoundError("user")
        document = self._normalize_definition(
            definition,
            timezone=user.timezone,
        )
        if document.title is None or document.start_date is None:
            raise DomainError("PLAN_VALIDATION_FAILED", "The plan definition is incomplete.")
        self._validator.validate(
            document,
            TrainingPlanValidationContext(user.timezone, pools, availability),
        )
        now = datetime.now(UTC).replace(microsecond=0)
        plan = TrainingPlan(
            id=EntityId.new(),
            user_id=user_id,
            goal_id=selected_goal.id,
            title=document.title,
            start_date=document.start_date,
            end_date=document.start_date + timedelta(days=document.duration_weeks * 7 - 1),
            duration_weeks=document.duration_weeks,
            prescription_source=PrescriptionSource.COACH_DEFINED,
            created_at=now,
            updated_at=now,
        )
        diff = plan_document_diff(None, document)
        proposal = ActionProposal.ready_for_review(
            id=EntityId.new(),
            user_id=user_id,
            action_type=self.ACTION_TYPE,
            target_type="training_plan",
            target_id=plan.id,
            target_revision_id=None,
            payload=cast(
                JsonObject,
                {
                    "expected_revision": 0,
                    "document": document.as_json(),
                    "reason": "Criação do ciclo",
                    "evidence": {},
                    "revision_kind": PlanRevisionKind.CREATION.value,
                    "decision": None,
                },
            ),
            impact=cast(
                JsonObject,
                {
                    "diff": diff,
                    "before_revision": 0,
                    "after_revision": 1,
                    "external_effects": [],
                    "approval_effect": "CREATE_PLAN_AND_MATERIALIZE_DETAILED_SESSIONS_LOCALLY",
                },
            ),
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        async with self._uow_factory() as uow:
            await uow.training_plans.add(plan)
            await uow.action_proposals.add(proposal)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="mcp",
                    actor_id=actor_id,
                    action="training_plan.proposed",
                    entity_type="TrainingPlan",
                    entity_id=plan.id,
                    correlation_id=correlation_id,
                    after={"proposal_id": str(proposal.id), "action_hash": proposal.action_hash},
                )
            )
            await uow.commit()
        return PlanProposalResult(plan, proposal, document)

    async def get_plan(self, user_id: UserId, plan_id: EntityId | None = None) -> PlanDetail:
        async with self._uow_factory() as uow:
            plan = (
                await uow.training_plans.get(user_id, plan_id)
                if plan_id is not None
                else await uow.training_plans.get_live(user_id)
            )
            if plan is None:
                raise ResourceNotFoundError("training_plan")
            revisions = tuple(await uow.training_plan_revisions.list(user_id, plan.id))
            bindings = tuple(await uow.plan_session_bindings.list_for_plan(user_id, plan.id))
            reviews = tuple(await uow.plan_reviews.list_for_plan(user_id, plan.id))
            notes = tuple(await uow.plan_notes.list_for_plan(user_id, plan.id))
        revision = revisions[-1] if revisions else None
        return PlanDetail(plan, revision, revisions, bindings, reviews, notes)

    async def review_week(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        week_number: int,
        correlation_id: CorrelationId,
    ) -> PlanReview:
        detail = await self.get_plan(user_id, plan_id)
        plan = detail.plan
        revision = detail.revision
        if revision is None or not 1 <= week_number <= plan.duration_weeks:
            raise DomainError("VALIDATION_FAILED", "The requested plan week is invalid.")
        week = revision.document.weeks[week_number - 1]
        if week.detail_level is not PlanDetailLevel.DETAILED:
            raise DomainError(
                "PLAN_WEEK_NOT_DETAILED",
                "Only the current detailed week can be reviewed for adaptation.",
            )
        current_week_intents = {
            item.session_intent_id for item in week.sessions if item.session_intent_id is not None
        }
        week_bindings = [
            item
            for item in detail.bindings
            if item.week_number == week_number
            and str(item.session_intent_id) in current_week_intents
            and item.state is not PlanSessionState.SUPERSEDED
        ]
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise ResourceNotFoundError("user")
            local_today = now.astimezone(ZoneInfo(user.timezone)).date()
            activities: list[JsonObject] = []
            completed_ids: set[EntityId] = set()
            quality_levels: list[str] = []
            comparable_samples = 0
            pain_signals: list[JsonObject] = []
            executed_distance = 0
            for binding in week_bindings:
                if binding.workout_id is None:
                    continue
                match = await uow.activity_data.get_match_by_workout(user_id, binding.workout_id)
                if match is None:
                    continue
                activity = await uow.activities.get(user_id, match.activity_id)
                analysis = await uow.activity_data.get_analysis(user_id, match.activity_id)
                feedback = await uow.activity_data.get_feedback(user_id, match.activity_id)
                if activity is None:
                    continue
                completed_ids.add(binding.session_intent_id)
                executed_distance += activity.distance.meters
                metrics = analysis.metrics if analysis is not None else {}
                raw_quality = metrics.get("data_quality")
                quality = (
                    str(raw_quality.get("level"))
                    if isinstance(raw_quality, dict) and raw_quality.get("level")
                    else (analysis.quality.value.upper() if analysis is not None else "LOW")
                )
                quality_levels.append(quality)
                raw_sets = metrics.get("sets")
                if isinstance(raw_sets, list):
                    comparable_samples += sum(
                        1
                        for item in raw_sets
                        if isinstance(item, dict)
                        and str(item.get("quality", "LOW")) in {"HIGH", "MEDIUM"}
                    )
                if feedback is not None and feedback.pain_present:
                    pain_signals.append(
                        {
                            "activity_ref": f"{activity.provider}:{activity.external_activity_id}",
                            "intensity": feedback.pain_intensity,
                            "location": feedback.pain_location,
                        }
                    )
                activities.append(
                    {
                        "activity_ref": f"{activity.provider}:{activity.external_activity_id}",
                        "workout_id": str(binding.workout_id),
                        "distance_m": activity.distance.meters,
                        "data_quality": (
                            raw_quality
                            if isinstance(raw_quality, dict)
                            else {"level": quality, "reasons": []}
                        ),
                        "metrics": {
                            "distance_adherence_ratio": metrics.get("distance_adherence_ratio"),
                            "planned_vs_actual": metrics.get("planned_vs_actual"),
                            "durations": metrics.get("durations"),
                            "paces": metrics.get("paces"),
                            "contextual_paces": metrics.get("contextual_paces"),
                            "continuity": metrics.get("continuity"),
                            "sets": raw_sets if isinstance(raw_sets, list) else [],
                            "consistency_cv": metrics.get("consistency_cv"),
                            "fade_percent": metrics.get("fade_percent"),
                            "total_rest_seconds": metrics.get("total_rest_seconds"),
                            "stroke_efficiency": metrics.get("stroke_efficiency"),
                            "speed_endurance": metrics.get("speed_endurance"),
                            "goal_readiness": metrics.get("goal_readiness"),
                            "longest_distance_below_goal_pace": metrics.get(
                                "longest_distance_below_goal_pace"
                            ),
                            "session_evaluation": metrics.get("session_evaluation"),
                            "srpe": metrics.get("srpe"),
                        },
                        "feedback": (
                            {
                                "rpe": feedback.rpe,
                                "technique_rating": feedback.technique_rating,
                                "fatigue_rating": feedback.fatigue_rating,
                                "feeling_score": feedback.feeling_score,
                                "pain_present": feedback.pain_present,
                                "pain_intensity": feedback.pain_intensity,
                                "comment": feedback.comment,
                            }
                            if feedback is not None
                            else None
                        ),
                    }
                )
            week_intent_refs = {str(item.session_intent_id) for item in week_bindings}
            activity_scope_refs = {
                str(item["activity_ref"])
                for item in activities
                if isinstance(item.get("activity_ref"), str)
            }
            notes = [
                {
                    "scope_type": item.scope_type.value,
                    "scope_ref": item.scope_ref,
                    "category": item.category.value,
                    "author_type": item.author_type.value,
                    "importance": item.importance.value,
                    "text": item.text,
                }
                for item in detail.notes
                if item.affects_adaptation
                and (item.valid_from is None or item.valid_from <= local_today)
                and (item.valid_until is None or item.valid_until >= local_today)
                and (
                    item.scope_type is NoteScope.PLAN
                    or (item.scope_type is NoteScope.WEEK and item.scope_ref == str(week_number))
                    or (item.scope_type is NoteScope.SESSION and item.scope_ref in week_intent_refs)
                    or (
                        item.scope_type is NoteScope.ACTIVITY
                        and item.scope_ref in activity_scope_refs
                    )
                )
            ]

        terminal_states = {
            PlanSessionState.COMPLETED,
            PlanSessionState.SKIPPED,
            PlanSessionState.CANCELLED,
        }
        resolved = all(
            item.state in terminal_states or item.session_intent_id in completed_ids
            for item in week_bindings
        ) and len(week_bindings) >= (week.session_count or len(week.sessions))
        week_end = plan.start_date + timedelta(days=week_number * 7 - 1)
        eligible = local_today > week_end or resolved
        reason = (
            "WEEK_ENDED"
            if local_today > week_end
            else "ALL_SESSIONS_RESOLVED"
            if resolved
            else "WEEK_OPEN"
        )
        if not activities or any(item == "LOW" for item in quality_levels):
            confidence = EvidenceConfidence.LOW
        elif len(activities) >= 2 and all(item == "HIGH" for item in quality_levels):
            confidence = EvidenceConfidence.HIGH
        else:
            confidence = EvidenceConfidence.MEDIUM
        planned_distance = sum(item.target_distance_m or 0 for item in week.sessions)
        evidence = cast(
            JsonObject,
            {
                "plan_revision": plan.current_revision,
                "week_number": week_number,
                "as_of_local_date": local_today.isoformat(),
                "eligibility_reason": reason,
                "planned_sessions": week.session_count or len(week.sessions),
                "completed_sessions": len(completed_ids),
                "skipped_sessions": sum(
                    item.state is PlanSessionState.SKIPPED for item in week_bindings
                ),
                "cancelled_sessions": sum(
                    item.state is PlanSessionState.CANCELLED for item in week_bindings
                ),
                "planned_distance_m": planned_distance,
                "executed_distance_m": executed_distance,
                "distance_adherence_ratio": (
                    float(Decimal(executed_distance) / Decimal(planned_distance))
                    if planned_distance
                    else None
                ),
                "comparable_evidence_count": comparable_samples,
                "pain_signals": pain_signals,
                "activities": activities,
                "notes": notes,
            },
        )
        review = PlanReview(
            id=EntityId.new(),
            user_id=user_id,
            plan_id=plan.id,
            plan_revision=plan.current_revision,
            week_number=week_number,
            evidence_snapshot=evidence,
            evidence_hash=canonical_json_hash(evidence),
            confidence_cap=confidence,
            eligible=eligible,
            eligibility_reason=reason,
        )
        async with self._uow_factory() as uow:
            stored = await uow.plan_reviews.add(review)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="mcp",
                    actor_id=actor_id,
                    action="training_plan.week_reviewed",
                    entity_type="TrainingPlan",
                    entity_id=plan.id,
                    correlation_id=correlation_id,
                    after={
                        "review_id": str(stored.id),
                        "week_number": week_number,
                        "evidence_hash": stored.evidence_hash,
                        "eligible": stored.eligible,
                    },
                )
            )
            await uow.commit()
        return stored

    async def propose_revision(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        expected_revision: int,
        revision_definition: TrainingPlanRevisionDefinition,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        detail = await self.get_plan(user_id, plan_id)
        plan = detail.plan
        current = detail.revision
        if current is None or plan.current_revision != expected_revision:
            raise DomainError("PLAN_REVISION_CONFLICT", "The plan revision changed.")
        if plan.status is not PlanStatus.ACTIVE:
            raise DomainError("PLAN_NOT_ACTIVE", "Only an active plan can be adapted.")
        review: PlanReview | None = None
        reviewed_week: int | None = None
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            pools = tuple(await uow.pools.list(user_id))
            availability = tuple(await uow.availability.list(user_id))
            if revision_definition.review_id is not None:
                review = await uow.plan_reviews.get(
                    user_id, EntityId.parse(revision_definition.review_id)
                )
            immutable_ids: set[str] = set()
            for binding in detail.bindings:
                if binding.workout_id is None:
                    continue
                if await uow.activity_data.get_match_by_workout(user_id, binding.workout_id):
                    immutable_ids.add(str(binding.session_intent_id))
        if user is None:
            raise ResourceNotFoundError("user")
        if revision_definition.kind == PlanRevisionKind.ADAPTATION.value:
            if (
                review is None
                or review.plan_id != plan.id
                or review.plan_revision != expected_revision
            ):
                raise ResourceNotFoundError("plan_review")
            if not review.eligible:
                raise DomainError("PLAN_REVIEW_NOT_ELIGIBLE", "The plan week is still open.")
            reviewed_week = review.week_number
        candidate = self._normalize_definition(
            revision_definition.definition,
            timezone=user.timezone,
        )
        identity_issues: list[JsonObject] = []
        for field_name, value, expected in (
            ("goal_id", candidate.goal_id, str(plan.goal_id)),
            ("title", candidate.title, plan.title),
            ("start_date", candidate.start_date, plan.start_date),
            ("duration_weeks", candidate.duration_weeks, plan.duration_weeks),
            ("timezone", candidate.timezone, user.timezone),
        ):
            if value != expected:
                identity_issues.append(
                    {
                        "code": "PLAN_METADATA_IMMUTABLE",
                        "path": f"definition.{field_name}",
                        "message": "Plan identity metadata cannot change in a revision.",
                    }
                )
        if identity_issues:
            raise DomainError(
                "PLAN_VALIDATION_FAILED",
                "The coach-authored training plan is invalid.",
                details=cast(JsonObject, {"issues": identity_issues}),
            )
        local_today = datetime.now(UTC).astimezone(ZoneInfo(user.timezone)).date()
        self._validator.validate(
            candidate,
            TrainingPlanValidationContext(user.timezone, pools, availability),
            previous=current.document,
            bindings=detail.bindings,
            immutable_session_ids=frozenset(immutable_ids),
            reviewed_week=reviewed_week,
            revision_kind=revision_definition.kind,
            local_today=local_today,
        )
        diff = plan_document_diff(current.document, candidate)
        status_after = (
            PlanStatus.PAUSED
            if revision_definition.decision is PlanDecision.PAUSE
            else PlanStatus.ACTIVE
        )
        now = datetime.now(UTC).replace(microsecond=0)
        proposal = ActionProposal.ready_for_review(
            id=EntityId.new(),
            user_id=user_id,
            action_type=self.ACTION_TYPE,
            target_type="training_plan",
            target_id=plan.id,
            target_revision_id=None,
            payload=cast(
                JsonObject,
                {
                    "expected_revision": expected_revision,
                    "document": candidate.as_json(),
                    "reason": revision_definition.rationale.strip(),
                    "evidence": review.evidence_snapshot if review is not None else {},
                    "review_id": str(review.id) if review is not None else None,
                    "decision": (
                        revision_definition.decision.value
                        if revision_definition.decision is not None
                        else None
                    ),
                    "confidence": review.confidence_cap.value if review is not None else None,
                    "revision_kind": revision_definition.kind,
                },
            ),
            impact=cast(
                JsonObject,
                {
                    "diff": diff,
                    "before_revision": expected_revision,
                    "after_revision": expected_revision + 1,
                    "external_effects": [],
                    "approval_effect": "APPLY_EXACT_COACH_DEFINED_REVISION",
                    "plan_status_after": status_after.value,
                },
            ),
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        async with self._uow_factory() as uow:
            existing_proposal = await uow.action_proposals.get_by_hash(
                user_id, proposal.action_hash
            )
            if existing_proposal is not None:
                return PlanProposalResult(plan, existing_proposal, candidate)
            await uow.action_proposals.add(proposal)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="mcp",
                    actor_id=actor_id,
                    action="training_plan.revision_proposed",
                    entity_type="TrainingPlan",
                    entity_id=plan.id,
                    correlation_id=correlation_id,
                    before={"revision": expected_revision},
                    after={
                        "proposal_id": str(proposal.id),
                        "decision": (
                            revision_definition.decision.value
                            if revision_definition.decision is not None
                            else None
                        ),
                        "revision_kind": revision_definition.kind,
                        "action_hash": proposal.action_hash,
                    },
                )
            )
            await uow.commit()
        return PlanProposalResult(plan, proposal, candidate)

    async def apply_revision(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        proposal_id: EntityId,
        expected_revision: int,
        approval_hash: str,
        correlation_id: CorrelationId,
    ) -> AppliedPlanRevision:
        now = datetime.now(UTC).replace(microsecond=0)
        async with self._uow_factory() as uow:
            await uow.idempotency.lock("training-plan-live", str(user_id))
            plan = await uow.training_plans.get_for_update(user_id, plan_id)
            proposal = await uow.action_proposals.get_for_update(user_id, proposal_id)
            if plan is None:
                raise ResourceNotFoundError("training_plan")
            live_plan = await uow.training_plans.get_live(user_id)
            if (
                plan.status is PlanStatus.DRAFT
                and live_plan is not None
                and live_plan.id != plan.id
            ):
                raise DomainError(
                    "ACTIVE_PLAN_EXISTS",
                    "Another training cycle is already active or paused.",
                )
            if (
                proposal is None
                or proposal.target_id != plan.id
                or proposal.action_type != self.ACTION_TYPE
            ):
                raise ResourceNotFoundError("action_proposal")
            payload_revision = proposal.payload.get("expected_revision")
            if (
                not isinstance(payload_revision, int)
                or payload_revision != expected_revision
                or plan.current_revision != expected_revision
            ):
                raise DomainError("PLAN_REVISION_CONFLICT", "The plan revision changed.")
            raw_document = proposal.payload.get("document")
            if not isinstance(raw_document, dict):
                raise DomainError("ACTION_TAMPERED", "The plan proposal is incomplete.")
            document = TrainingPlanDocument.model_validate(raw_document)
            if document.schema_version != "2.0":
                raise DomainError(
                    "LEGACY_RULESET_READ_ONLY",
                    "Legacy ruleset proposals cannot be applied after coach-defined "
                    "planning is enabled.",
                )
            existing_revision = (
                await uow.training_plan_revisions.get(user_id, plan.id, expected_revision)
                if expected_revision > 0
                else None
            )
            if expected_revision > 0 and existing_revision is None:
                raise DomainError("PLAN_REVISION_CONFLICT", "The current plan revision is missing.")
            user = await uow.users.get(user_id)
            if user is None:
                raise ResourceNotFoundError("user")
            pools = tuple(await uow.pools.list(user_id))
            availability = tuple(await uow.availability.list(user_id))
            bindings = tuple(await uow.plan_session_bindings.list_for_plan(user_id, plan.id))
            immutable_ids: set[str] = set()
            for binding in bindings:
                if binding.workout_id is not None and await uow.activity_data.get_match_by_workout(
                    user_id, binding.workout_id
                ):
                    immutable_ids.add(str(binding.session_intent_id))
            self._validator.validate(
                document,
                TrainingPlanValidationContext(user.timezone, pools, availability),
                previous=existing_revision.document if existing_revision is not None else None,
                bindings=bindings,
                immutable_session_ids=frozenset(immutable_ids),
                revision_kind=str(proposal.payload.get("revision_kind") or "CREATION"),
                local_today=now.astimezone(ZoneInfo(user.timezone)).date(),
            )
            expected_plan_version = plan.version
            expected_proposal_version = proposal.version
            proposal.approve(action_hash=approval_hash, now=now)
            await uow.action_approvals.add(
                ActionApproval(
                    id=EntityId.new(),
                    proposal_id=proposal.id,
                    user_id=user_id,
                    action_hash=approval_hash,
                    decision=ActionDecision.APPROVE,
                    explicit_verb="apply_plan_revision",
                    created_at=now,
                )
            )
            proposal.queue(now)
            proposal.start(now)
            revision = TrainingPlanRevision(
                id=EntityId.new(),
                plan_id=plan.id,
                revision_number=expected_revision + 1,
                previous_revision_id=existing_revision.id if existing_revision else None,
                document=document,
                content_hash=document.content_hash,
                reason=str(proposal.payload.get("reason") or "Revisão aprovada"),
                revision_kind=PlanRevisionKind(
                    str(proposal.payload.get("revision_kind") or PlanRevisionKind.CREATION.value)
                ),
                decision=(
                    PlanDecision(str(proposal.payload["decision"]))
                    if proposal.payload.get("decision") is not None
                    else None
                ),
                effective_from=self._detailed_week_start(plan, document),
                evidence=cast(JsonObject, proposal.payload.get("evidence") or {}),
                diff=cast(JsonObject, proposal.impact.get("diff") or {}),
                proposal_id=proposal.id,
                created_by=actor_id,
                created_at=now,
            )
            await uow.training_plan_revisions.add(revision)
            await uow.flush()
            plan.apply_revision(revision, now)
            plan.prescription_source = PrescriptionSource.COACH_DEFINED
            if proposal.payload.get("decision") == PlanDecision.PAUSE.value:
                plan.set_status(PlanStatus.PAUSED, now)
            await uow.training_plans.update(plan, expected_version=expected_plan_version)
            supplied_intents: dict[EntityId, int] = {}
            superseded_session_ids: list[str] = []
            locally_unscheduled_workout_ids: list[str] = []
            for week in document.weeks:
                for session in week.sessions:
                    if session.session_intent_id is None:
                        raise DomainError("ACTION_TAMPERED", "A plan session identity is missing.")
                    intent_id = EntityId.parse(session.session_intent_id)
                    supplied_intents[intent_id] = week.week_number
                    existing_binding = await uow.plan_session_bindings.get_by_intent(
                        user_id, plan.id, intent_id
                    )
                    if existing_binding is None:
                        await uow.plan_session_bindings.add(
                            PlanSessionBinding(
                                id=EntityId.new(),
                                user_id=user_id,
                                plan_id=plan.id,
                                session_intent_id=intent_id,
                                week_number=week.week_number,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    elif (
                        existing_binding.week_number != week.week_number
                        or existing_binding.state is PlanSessionState.SUPERSEDED
                    ):
                        previous_binding_version = existing_binding.version
                        existing_binding.week_number = week.week_number
                        if existing_binding.state is PlanSessionState.SUPERSEDED:
                            existing_binding.state = (
                                PlanSessionState.MATERIALIZED
                                if existing_binding.workout_id is not None
                                else PlanSessionState.PLANNED
                            )
                        existing_binding.updated_at = now
                        existing_binding.version += 1
                        await uow.plan_session_bindings.update(
                            existing_binding,
                            expected_version=previous_binding_version,
                        )
            for existing_binding in bindings:
                if (
                    existing_binding.session_intent_id in supplied_intents
                    or existing_binding.locked
                    or existing_binding.state is PlanSessionState.SUPERSEDED
                ):
                    continue
                if (
                    existing_binding.workout_id is not None
                    and await uow.activity_data.get_match_by_workout(
                        user_id, existing_binding.workout_id
                    )
                    is not None
                ):
                    raise DomainError(
                        "PLAN_SESSION_LOCKED",
                        "An activity-linked session cannot be removed from the plan.",
                    )
                previous_binding_version = existing_binding.version
                existing_binding.state = PlanSessionState.SUPERSEDED
                existing_binding.updated_at = now
                existing_binding.version += 1
                await uow.plan_session_bindings.update(
                    existing_binding,
                    expected_version=previous_binding_version,
                )
                superseded_session_ids.append(str(existing_binding.session_intent_id))
                if existing_binding.workout_id is not None:
                    workout = await uow.workouts.get(user_id, existing_binding.workout_id)
                    schedule_removed = await uow.workout_schedules.delete(
                        user_id, existing_binding.workout_id
                    )
                    if workout is not None and schedule_removed:
                        previous_workout_version = workout.version
                        workout.schedule = None
                        if workout.status is PlannedWorkoutStatus.SCHEDULED:
                            workout.status = PlannedWorkoutStatus.APPROVED
                        workout.updated_at = now
                        workout.version += 1
                        await uow.workouts.update(
                            workout,
                            expected_version=previous_workout_version,
                        )
                        locally_unscheduled_workout_ids.append(str(workout.id))
            jobs: list[Job] = []
            if plan.status is PlanStatus.ACTIVE:
                materializable_week_numbers = {
                    week.week_number
                    for week in document.weeks
                    if week.detail_level is PlanDetailLevel.DETAILED
                    and (
                        existing_revision is None
                        or existing_revision.document.weeks[week.week_number - 1] != week
                    )
                }
                for detailed_week in (
                    item
                    for item in document.weeks
                    if item.week_number in materializable_week_numbers
                ):
                    jobs.append(
                        await uow.jobs.add_idempotent(
                            Job(
                                id=EntityId.new(),
                                user_id=user_id,
                                job_type=self.MATERIALIZE_JOB_TYPE,
                                payload={
                                    "plan_id": str(plan.id),
                                    "revision": revision.revision_number,
                                    "week_number": detailed_week.week_number,
                                },
                                idempotency_key=(
                                    f"plan-materialize:{plan.id}:{revision.revision_number}:"
                                    f"{detailed_week.week_number}"
                                ),
                                max_attempts=3,
                            )
                        )
                    )
            proposal.succeed(now)
            await uow.action_proposals.update(proposal, expected_version=expected_proposal_version)
            event_payload = cast(
                JsonObject,
                {
                    "plan_id": str(plan.id),
                    "revision": revision.revision_number,
                    "proposal_id": str(proposal.id),
                    "materialization_job_ids": [str(job.id) for job in jobs],
                    "superseded_session_ids": superseded_session_ids,
                    "locally_unscheduled_workout_ids": locally_unscheduled_workout_ids,
                    "garmin_changed": False,
                },
            )
            await uow.outbox.add(
                OutboxEvent(
                    id=EntityId.new(),
                    aggregate_type="TrainingPlan",
                    aggregate_id=plan.id,
                    event_type="swim_coach.training_plan.revised.v1",
                    payload=event_payload,
                    user_id=user_id,
                    correlation_id=correlation_id,
                )
            )
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action="training_plan.revision_applied",
                    entity_type="TrainingPlan",
                    entity_id=plan.id,
                    correlation_id=correlation_id,
                    before={"revision": expected_revision},
                    after=event_payload,
                )
            )
            await uow.commit()
        return AppliedPlanRevision(
            plan,
            revision,
            tuple(job.id for job in jobs),
            tuple(EntityId.parse(item) for item in superseded_session_ids),
            tuple(EntityId.parse(item) for item in locally_unscheduled_workout_ids),
        )

    async def materialize_week(
        self,
        user_id: UserId,
        *,
        plan_id: EntityId,
        expected_revision: int,
        week_number: int,
        correlation_id: CorrelationId,
    ) -> MaterializationResult:
        detail = await self.get_plan(user_id, plan_id)
        if detail.revision is None or detail.plan.current_revision != expected_revision:
            raise DomainError("PLAN_REVISION_CONFLICT", "The plan revision changed.")
        if detail.plan.status is not PlanStatus.ACTIVE:
            raise DomainError("PLAN_NOT_ACTIVE", "Only an active plan can materialize a week.")
        if not 1 <= week_number <= detail.plan.duration_weeks:
            raise DomainError("VALIDATION_FAILED", "The requested plan week is invalid.")
        week = detail.revision.document.weeks[week_number - 1]
        if week.detail_level is not PlanDetailLevel.DETAILED:
            raise DomainError(
                "PLAN_WEEK_NOT_DETAILED", "Only the detailed horizon can materialize."
            )
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            pools = await uow.pools.list(user_id)
        if user is None:
            raise ResourceNotFoundError("user")
        active_pools = {str(item.id): item for item in pools if item.active}
        if not active_pools:
            raise DomainError("POOL_REQUIRED", "Configure an active pool before materializing.")

        created: list[EntityId] = []
        skipped: list[EntityId] = []
        replayed = True
        for intent in week.sessions:
            if intent.session_intent_id is None:
                raise DomainError("INTERNAL_ERROR", "The plan session identity is missing.")
            intent_id = EntityId.parse(intent.session_intent_id)
            if intent.workout is None:
                raise DomainError("INTERNAL_ERROR", "A detailed plan session has no workout.")
            definition = CanonicalWorkout.model_validate(intent.workout)
            pool = active_pools.get(intent.pool_id or "")
            if pool is None:
                raise DomainError("POOL_REQUIRED", "The plan session pool is not active.")
            if definition.pool_length_m != pool.length.meters:
                raise DomainError("POOL_MISMATCH", "The plan workout uses another pool length.")
            async with self._uow_factory() as uow:
                binding = await uow.plan_session_bindings.get_by_intent(user_id, plan_id, intent_id)
            if binding is None:
                raise DomainError("INTERNAL_ERROR", "The plan session binding is missing.")
            if binding.locked:
                skipped.append(intent_id)
                continue
            if binding.workout_id is not None:
                async with self._uow_factory() as uow:
                    activity_match = await uow.activity_data.get_match_by_workout(
                        user_id, binding.workout_id
                    )
                if activity_match is not None:
                    skipped.append(intent_id)
                    continue
            content_hash = canonical_content_hash(definition)
            workout_id = binding.workout_id
            if workout_id is None:
                replayed = False
                workout = await self._workouts.create_draft(
                    user_id,
                    definition,
                    pool_id=pool.id,
                    correlation_id=correlation_id,
                    workout_id=EntityId(uuid5(plan_id.value, str(intent_id))),
                )
            else:
                workout = await self._workouts.get_workout(user_id, workout_id)
                current_hash = workout.current_revision.content_hash
                if (
                    binding.materialized_workout_hash is not None
                    and current_hash != binding.materialized_workout_hash
                    and current_hash != content_hash
                ):
                    async with self._uow_factory() as uow:
                        current = await uow.plan_session_bindings.get_by_intent(
                            user_id, plan_id, intent_id
                        )
                        if current is not None:
                            previous = current.version
                            current.locked_reason = "MANUAL_WORKOUT_EDIT"
                            current.updated_at = datetime.now(UTC)
                            current.version += 1
                            await uow.plan_session_bindings.update(
                                current, expected_version=previous
                            )
                            await uow.commit()
                    skipped.append(intent_id)
                    continue
                if current_hash != content_hash:
                    replayed = False
                    workout = await self._workouts.revise(
                        user_id,
                        workout_id,
                        definition,
                        expected_version=workout.workout.version,
                        change_reason="Revisão aprovada do ciclo",
                        correlation_id=correlation_id,
                    )
            if workout.workout.current_revision_id != workout.workout.approved_revision_id:
                replayed = False
                workout = await self._workouts.approve_local(
                    user_id,
                    workout.workout.id,
                    expected_version=workout.workout.version,
                    expected_content_hash=workout.current_revision.content_hash,
                    correlation_id=correlation_id,
                )
            if intent.scheduled_date is None:
                raise DomainError("INTERNAL_ERROR", "A detailed plan session has no date.")
            if (
                workout.schedule is not None
                and (
                    workout.schedule.scheduled_date != intent.scheduled_date
                    or workout.schedule.scheduled_start_time != intent.scheduled_start_time
                    or workout.schedule.pool_id != pool.id
                )
                and binding.materialized_plan_revision == expected_revision
            ):
                async with self._uow_factory() as uow:
                    current = await uow.plan_session_bindings.get_by_intent(
                        user_id, plan_id, intent_id
                    )
                    if current is not None:
                        previous = current.version
                        current.locked_reason = "MANUAL_SCHEDULE_EDIT"
                        current.updated_at = datetime.now(UTC)
                        current.version += 1
                        await uow.plan_session_bindings.update(current, expected_version=previous)
                        await uow.commit()
                skipped.append(intent_id)
                continue
            if workout.schedule is None or (
                workout.schedule.scheduled_date != intent.scheduled_date
                or workout.schedule.scheduled_start_time != intent.scheduled_start_time
                or workout.schedule.pool_id != pool.id
            ):
                replayed = False
                workout = await self._workouts.schedule(
                    user_id,
                    workout.workout.id,
                    scheduled_date=intent.scheduled_date,
                    scheduled_start_time=intent.scheduled_start_time,
                    timezone=user.timezone,
                    pool_id=pool.id,
                    expected_version=workout.workout.version,
                    correlation_id=correlation_id,
                )
            async with self._uow_factory() as uow:
                current = await uow.plan_session_bindings.get_by_intent(user_id, plan_id, intent_id)
                if current is None:
                    raise DomainError("INTERNAL_ERROR", "The plan session binding disappeared.")
                previous = current.version
                current.workout_id = workout.workout.id
                current.state = PlanSessionState.MATERIALIZED
                current.materialized_plan_revision = expected_revision
                current.materialized_workout_hash = workout.current_revision.content_hash
                current.updated_at = datetime.now(UTC)
                current.version += 1
                await uow.plan_session_bindings.update(current, expected_version=previous)
                await uow.commit()
            created.append(workout.workout.id)
        return MaterializationResult(
            plan_id,
            expected_revision,
            week_number,
            tuple(created),
            tuple(skipped),
            replayed,
        )

    async def add_note(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        scope_type: NoteScope,
        scope_ref: str,
        category: NoteCategory,
        author_type: NoteAuthor,
        text: str,
        importance: NoteImportance,
        affects_adaptation: bool,
        valid_from: date | None,
        valid_until: date | None,
        evidence_activity_ids: tuple[EntityId, ...],
        correlation_id: CorrelationId,
    ) -> PlanNote:
        detail = await self.get_plan(user_id, plan_id)
        normalized_scope_ref = scope_ref.strip()
        if scope_type is NoteScope.PLAN:
            normalized_scope_ref = str(plan_id)
        if scope_type is NoteScope.WEEK:
            try:
                week_number = int(normalized_scope_ref)
            except ValueError as exc:
                raise DomainError("VALIDATION_FAILED", "Week scope_ref must be a number.") from exc
            if not 1 <= week_number <= detail.plan.duration_weeks:
                raise DomainError("VALIDATION_FAILED", "Week scope_ref is outside the plan.")
        if scope_type is NoteScope.SESSION:
            try:
                intent_id = EntityId.parse(normalized_scope_ref)
            except ValueError as exc:
                raise DomainError("VALIDATION_FAILED", "Session scope_ref must be a UUID.") from exc
            if not any(item.session_intent_id == intent_id for item in detail.bindings):
                raise DomainError("VALIDATION_FAILED", "Session scope_ref is outside the plan.")
        activity_refs: list[str] = []
        async with self._uow_factory() as uow:
            if scope_type is NoteScope.ACTIVITY:
                try:
                    scoped_activity_id = EntityId.parse(normalized_scope_ref)
                except ValueError as exc:
                    raise DomainError(
                        "VALIDATION_FAILED", "Activity scope_ref must be a UUID."
                    ) from exc
                scoped_activity = await uow.activities.get(user_id, scoped_activity_id)
                if scoped_activity is None:
                    raise ResourceNotFoundError("activity")
                normalized_scope_ref = (
                    f"{scoped_activity.provider}:{scoped_activity.external_activity_id}"
                )
            for activity_id in evidence_activity_ids:
                activity = await uow.activities.get(user_id, activity_id)
                if activity is None:
                    raise ResourceNotFoundError("activity")
                activity_refs.append(f"{activity.provider}:{activity.external_activity_id}")
        note = PlanNote(
            id=EntityId.new(),
            user_id=user_id,
            plan_id=plan_id,
            scope_type=scope_type,
            scope_ref=normalized_scope_ref,
            category=category,
            author_type=author_type,
            text=text,
            importance=importance,
            affects_adaptation=affects_adaptation,
            valid_from=valid_from,
            valid_until=valid_until,
            evidence_activity_refs=tuple(activity_refs),
        )
        async with self._uow_factory() as uow:
            await uow.plan_notes.add(note)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action="training_plan.note_added",
                    entity_type="TrainingPlan",
                    entity_id=plan_id,
                    correlation_id=correlation_id,
                    after={"note_id": str(note.id), "category": category.value},
                )
            )
            await uow.commit()
        return note

    async def set_status(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan_id: EntityId,
        status: PlanStatus,
        correlation_id: CorrelationId,
    ) -> TrainingPlan:
        if status not in {PlanStatus.ACTIVE, PlanStatus.PAUSED}:
            raise DomainError("VALIDATION_FAILED", "Only pause and resume are exposed here.")
        now = datetime.now(UTC)
        async with self._uow_factory() as uow:
            plan = await uow.training_plans.get_for_update(user_id, plan_id)
            if plan is None:
                raise ResourceNotFoundError("training_plan")
            previous = plan.version
            plan.set_status(status, now)
            await uow.training_plans.update(plan, expected_version=previous)
            await uow.audit.add(
                AuditEvent(
                    id=EntityId.new(),
                    user_id=user_id,
                    actor_type="user",
                    actor_id=actor_id,
                    action=f"training_plan.{status.value.lower()}",
                    entity_type="TrainingPlan",
                    entity_id=plan.id,
                    correlation_id=correlation_id,
                    after={"status": status.value},
                )
            )
            await uow.commit()
        return plan

    async def skip_session(
        self,
        user_id: UserId,
        *,
        plan_id: EntityId,
        session_intent_id: EntityId,
    ) -> PlanSessionBinding:
        async with self._uow_factory() as uow:
            binding = await uow.plan_session_bindings.get_by_intent(
                user_id, plan_id, session_intent_id
            )
            if binding is None:
                raise ResourceNotFoundError("plan_session")
            if binding.state in {
                PlanSessionState.COMPLETED,
                PlanSessionState.CANCELLED,
                PlanSessionState.SUPERSEDED,
            }:
                raise DomainError("PLAN_SESSION_LOCKED", "The plan session is already resolved.")
            if binding.workout_id is not None:
                match = await uow.activity_data.get_match_by_workout(user_id, binding.workout_id)
                if match is not None:
                    raise DomainError(
                        "PLAN_SESSION_LOCKED", "A completed session cannot be skipped."
                    )
            previous = binding.version
            binding.state = PlanSessionState.SKIPPED
            binding.locked_reason = "ATHLETE_SKIPPED"
            binding.updated_at = datetime.now(UTC)
            binding.version += 1
            await uow.plan_session_bindings.update(binding, expected_version=previous)
            await uow.commit()
        return binding

    @staticmethod
    def _normalize_definition(
        definition: TrainingPlanDocument,
        *,
        timezone: str,
    ) -> TrainingPlanDocument:
        weeks: list[PlanWeek] = []
        for week in definition.weeks:
            sessions: list[PlanSessionIntent] = []
            for session in week.sessions:
                sessions.append(
                    session.model_copy(
                        update={
                            "session_intent_id": session.session_intent_id or str(EntityId.new()),
                        }
                    )
                )
            weeks.append(week.model_copy(update={"sessions": tuple(sessions)}))
        normalized = definition.model_copy(
            update={
                "timezone": definition.timezone or timezone,
                "weeks": tuple(weeks),
            }
        )
        return TrainingPlanDocument.model_validate(normalized.as_json())

    @staticmethod
    def _detailed_week_start(plan: TrainingPlan, document: TrainingPlanDocument) -> date | None:
        detailed = next(
            (item for item in document.weeks if item.detail_level is PlanDetailLevel.DETAILED), None
        )
        return (
            plan.start_date + timedelta(days=(detailed.week_number - 1) * 7)
            if detailed is not None
            else None
        )
