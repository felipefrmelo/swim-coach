"""Application workflows for approval-gated rolling training cycles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid5
from zoneinfo import ZoneInfo

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.planning import PlanningService
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
    PlanningPreferences,
    PlanNote,
    PlanPhase,
    PlanReview,
    PlanSessionBinding,
    PlanSessionIntent,
    PlanSessionState,
    PlanStatus,
    PlanWeek,
    TrainingPlan,
    TrainingPlanDocument,
    TrainingPlanRevision,
    canonical_json_hash,
    plan_document_diff,
)
from swim_coach.domain.shared.errors import DomainError, ResourceNotFoundError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.shared.value_objects import CorrelationId, EntityId, UserId
from swim_coach.domain.workouts import (
    CanonicalWorkout,
    canonical_content_hash,
    validate_workout,
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
    materialization_job_id: EntityId | None


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
        planning: PlanningService,
        workouts: WorkoutService,
    ) -> None:
        self._uow_factory = uow_factory
        self._planning = planning
        self._workouts = workouts

    async def propose_plan(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        goal_id: EntityId | None,
        title: str | None,
        start_date: date,
        duration_weeks: int,
        strategy_summary: str | None,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        if start_date.weekday() != 0:
            raise DomainError("VALIDATION_FAILED", "Plan start_date must be a Monday.")
        if not 4 <= duration_weeks <= 16:
            raise DomainError("VALIDATION_FAILED", "Plan duration must be between 4 and 16 weeks.")
        async with self._uow_factory() as uow:
            if await uow.training_plans.get_live(user_id) is not None:
                raise DomainError(
                    "ACTIVE_PLAN_EXISTS",
                    "Pause, complete, or cancel the current plan before starting another cycle.",
                )
            goals = await uow.goals.list(user_id)
            selected_goal = (
                next((item for item in goals if item.id == goal_id), None)
                if goal_id is not None
                else next((item for item in goals if item.status is GoalStatus.ACTIVE), None)
            )
        if selected_goal is None or selected_goal.status is not GoalStatus.ACTIVE:
            raise DomainError("GOAL_REQUIRED", "Choose an active goal before creating a plan.")

        run, _, _ = await self._planning.propose_week(
            user_id,
            actor_id=actor_id,
            week_start=start_date,
            preferences=PlanningPreferences(),
            user_notes_present=False,
            correlation_id=correlation_id,
            create_proposal=False,
        )
        document = self._initial_document(
            run.input_snapshot,
            run.output_plan,
            duration_weeks=duration_weeks,
            strategy_summary=strategy_summary,
        )
        self._validate_document(start_date, document)
        now = datetime.now(UTC).replace(microsecond=0)
        plan = TrainingPlan(
            id=EntityId.new(),
            user_id=user_id,
            goal_id=selected_goal.id,
            title=(title or f"Ciclo para {selected_goal.title}").strip(),
            start_date=start_date,
            end_date=start_date + timedelta(days=duration_weeks * 7 - 1),
            duration_weeks=duration_weeks,
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
                    "document": document.model_dump(mode="json"),
                    "reason": "Criação do ciclo",
                    "evidence": document.baseline_snapshot,
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
                    "approval_effect": "CREATE_PLAN_AND_QUEUE_LOCAL_MATERIALIZATION",
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
        week_bindings = [item for item in detail.bindings if item.week_number == week_number]
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
                        "data_quality": quality,
                        "metrics": {
                            "distance_adherence_ratio": metrics.get("distance_adherence_ratio"),
                            "continuity": metrics.get("continuity"),
                            "sets": raw_sets if isinstance(raw_sets, list) else [],
                            "session_evaluation": metrics.get("session_evaluation"),
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
        resolved = (
            all(
                item.state in terminal_states or item.session_intent_id in completed_ids
                for item in week_bindings
            )
            and len(week_bindings) >= week.session_count
        )
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
        planned_distance = sum(item.target_distance_m for item in week.sessions)
        evidence = cast(
            JsonObject,
            {
                "plan_revision": plan.current_revision,
                "week_number": week_number,
                "as_of_local_date": local_today.isoformat(),
                "eligibility_reason": reason,
                "planned_sessions": week.session_count,
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
            for binding in week_bindings:
                if (
                    binding.session_intent_id not in completed_ids
                    or binding.state is PlanSessionState.COMPLETED
                ):
                    continue
                current_binding = await uow.plan_session_bindings.get_by_intent(
                    user_id, plan.id, binding.session_intent_id
                )
                if current_binding is None:
                    continue
                previous_version = current_binding.version
                current_binding.state = PlanSessionState.COMPLETED
                current_binding.locked_reason = "ACTIVITY_MATCHED"
                current_binding.updated_at = now
                current_binding.version += 1
                await uow.plan_session_bindings.update(
                    current_binding, expected_version=previous_version
                )
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
        review_id: EntityId,
        expected_revision: int,
        decision: PlanDecision,
        rationale: str,
        correlation_id: CorrelationId,
    ) -> PlanProposalResult:
        detail = await self.get_plan(user_id, plan_id)
        plan = detail.plan
        current = detail.revision
        if current is None or plan.current_revision != expected_revision:
            raise DomainError("PLAN_REVISION_CONFLICT", "The plan revision changed.")
        if plan.status is not PlanStatus.ACTIVE:
            raise DomainError("PLAN_NOT_ACTIVE", "Only an active plan can be adapted.")
        async with self._uow_factory() as uow:
            review = await uow.plan_reviews.get(user_id, review_id)
        if review is None or review.plan_id != plan.id or review.plan_revision != expected_revision:
            raise ResourceNotFoundError("plan_review")
        if not review.eligible:
            raise DomainError("PLAN_REVIEW_NOT_ELIGIBLE", "The plan week is still open.")
        self._validate_decision(review, decision)
        candidate = await self._roll_document(
            user_id,
            actor_id=actor_id,
            plan=plan,
            current=current.document,
            reviewed_week=review.week_number,
            decision=decision,
            correlation_id=correlation_id,
        )
        self._validate_candidate(
            current.document,
            candidate,
            reviewed_week=review.week_number,
            bindings=detail.bindings,
        )
        self._validate_document(plan.start_date, candidate)
        diff = plan_document_diff(current.document, candidate)
        status_after = (
            PlanStatus.PAUSED
            if decision is PlanDecision.PAUSE
            else PlanStatus.COMPLETED
            if review.week_number == plan.duration_weeks
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
                    "document": candidate.model_dump(mode="json"),
                    "reason": rationale.strip(),
                    "evidence": review.evidence_snapshot,
                    "review_id": str(review.id),
                    "decision": decision.value,
                    "confidence": review.confidence_cap.value,
                },
            ),
            impact=cast(
                JsonObject,
                {
                    "diff": diff,
                    "before_revision": expected_revision,
                    "after_revision": expected_revision + 1,
                    "external_effects": [],
                    "approval_effect": "REVISE_PLAN_AND_QUEUE_LOCAL_MATERIALIZATION",
                    "plan_status_after": status_after.value,
                },
            ),
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        recommendation = review.with_recommendation(
            decision=decision,
            rationale=rationale,
            recommendation=cast(
                JsonObject,
                {
                    "confidence": review.confidence_cap.value,
                    "diff": diff,
                    "impact": proposal.impact,
                },
            ),
            proposal_id=proposal.id,
        )
        async with self._uow_factory() as uow:
            await uow.action_proposals.add(proposal)
            await uow.plan_reviews.set_recommendation(recommendation)
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
                        "decision": decision.value,
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
            self._validate_document(plan.start_date, document)
            existing_revision = (
                await uow.training_plan_revisions.get(user_id, plan.id, expected_revision)
                if expected_revision > 0
                else None
            )
            if expected_revision > 0 and existing_revision is None:
                raise DomainError("PLAN_REVISION_CONFLICT", "The current plan revision is missing.")
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
            if proposal.payload.get("decision") == PlanDecision.PAUSE.value:
                plan.set_status(PlanStatus.PAUSED, now)
            elif not any(item.detail_level is PlanDetailLevel.DETAILED for item in document.weeks):
                plan.set_status(PlanStatus.COMPLETED, now)
            await uow.training_plans.update(plan, expected_version=expected_plan_version)
            for week in document.weeks:
                for session in week.sessions:
                    intent_id = EntityId.parse(session.session_intent_id)
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
            job: Job | None = None
            detailed_week = next(
                (item for item in document.weeks if item.detail_level is PlanDetailLevel.DETAILED),
                None,
            )
            if detailed_week is not None and plan.status is PlanStatus.ACTIVE:
                job = await uow.jobs.add_idempotent(
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
            proposal.succeed(now)
            await uow.action_proposals.update(proposal, expected_version=expected_proposal_version)
            event_payload: JsonObject = {
                "plan_id": str(plan.id),
                "revision": revision.revision_number,
                "proposal_id": str(proposal.id),
                "materialization_job_id": str(job.id) if job else None,
            }
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
        return AppliedPlanRevision(plan, revision, job.id if job else None)

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
        pool = next(
            (item for item in pools if item.active and item.is_default),
            next((item for item in pools if item.active), None),
        )
        if pool is None:
            raise DomainError("POOL_REQUIRED", "Configure an active pool before materializing.")

        created: list[EntityId] = []
        skipped: list[EntityId] = []
        replayed = True
        for intent in week.sessions:
            intent_id = EntityId.parse(intent.session_intent_id)
            definition = CanonicalWorkout.model_validate(intent.workout)
            if definition.pool_length_m != pool.length.meters:
                raise DomainError("POOL_MISMATCH", "The plan workout uses another pool length.")
            async with self._uow_factory() as uow:
                binding = await uow.plan_session_bindings.get_by_intent(user_id, plan_id, intent_id)
            if binding is None:
                raise DomainError("INTERNAL_ERROR", "The plan session binding is missing.")
            if binding.locked:
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
                and workout.schedule.scheduled_date != intent.scheduled_date
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
            if workout.schedule is None or workout.schedule.scheduled_date != intent.scheduled_date:
                replayed = False
                workout = await self._workouts.schedule(
                    user_id,
                    workout.workout.id,
                    scheduled_date=intent.scheduled_date,
                    scheduled_start_time=None,
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
    def _initial_document(
        input_snapshot: JsonObject,
        output_plan: JsonObject,
        *,
        duration_weeks: int,
        strategy_summary: str | None,
    ) -> TrainingPlanDocument:
        raw_context = input_snapshot.get("context")
        context = raw_context if isinstance(raw_context, dict) else {}
        sessions = TrainingCycleService._session_intents(output_plan)
        first_volume = TrainingCycleService._integer(
            output_plan.get("target_volume_m"),
            sum(item.target_distance_m for item in sessions),
        )
        weeks: list[PlanWeek] = []
        projected = first_volume
        projected_duration = sum(item.max_duration_minutes for item in sessions)
        phases = TrainingCycleService._phases(duration_weeks)
        for number in range(1, duration_weeks + 1):
            phase = next(item for item in phases if item.start_week <= number <= item.end_week)
            if number == 1:
                detail = PlanDetailLevel.DETAILED
                week_sessions = sessions
                session_count = len(sessions)
            elif number == 2:
                detail = PlanDetailLevel.OUTLINE
                week_sessions = ()
                session_count = len(sessions)
                projected = int(projected * 1.05)
            else:
                detail = PlanDetailLevel.STRATEGIC
                week_sessions = ()
                session_count = len(sessions)
                projected = int(projected * (0.82 if number % 4 == 0 else 1.05))
            pool_length = TrainingCycleService._integer(context.get("pool_length_m"), 20)
            projected -= projected % pool_length
            weeks.append(
                PlanWeek(
                    week_number=number,
                    focus=phase.focus,
                    detail_level=detail,
                    target_distance_min_m=max(
                        pool_length,
                        int(projected * 0.92) // pool_length * pool_length,
                    ),
                    target_distance_max_m=max(pool_length, projected),
                    target_duration_min_minutes=session_count * 20,
                    target_duration_max_minutes=projected_duration,
                    session_count=session_count,
                    load_target="RECOVERY" if number % 4 == 0 else "BUILD",
                    success_criteria=phase.success_criteria,
                    sessions=week_sessions,
                )
            )
        recent_weeks = context.get("recent_weeks")
        confidence = (
            EvidenceConfidence.MEDIUM
            if isinstance(recent_weeks, list) and recent_weeks
            else EvidenceConfidence.LOW
        )
        return TrainingPlanDocument(
            strategy_summary=(
                strategy_summary.strip()
                if strategy_summary and strategy_summary.strip()
                else (
                    "Ciclo em horizonte móvel: consolidar técnica e endurance antes de "
                    "testar a meta."
                )
            ),
            duration_weeks=duration_weeks,
            baseline_snapshot=cast(
                JsonObject,
                {
                    "goal": {
                        "id": context.get("goal_id"),
                        "title": context.get("goal_title"),
                        "target_distance_m": context.get("target_distance_m"),
                        "target_pace_seconds_per_100m": context.get("target_pace_seconds_per_100m"),
                    },
                    "recent_weeks": recent_weeks if isinstance(recent_weeks, list) else [],
                    "feedback": context.get("recent_feedback") or [],
                    "pool_length_m": context.get("pool_length_m"),
                },
            ),
            baseline_confidence=confidence,
            phases=phases,
            weeks=tuple(weeks),
            ruleset_version=str(output_plan.get("ruleset_version") or "unknown"),
            ruleset_hash=str(output_plan.get("ruleset_hash") or "0" * 64),
        )

    @staticmethod
    def _phases(duration: int) -> tuple[PlanPhase, ...]:
        ranges: tuple[tuple[str, int, int, str], ...]
        if duration == 8:
            ranges = (
                ("Baseline e técnica", 1, 2, "Técnica e consistência em 80-120 m"),
                ("Base", 3, 4, "Blocos de 120-200 m e primeiro checkpoint"),
                ("Endurance", 5, 6, "Séries de 200-400 m e continuidade"),
                ("Específica", 7, 7, "Trabalho específico conforme as evidências"),
                ("Checkpoint", 8, 8, "Teste de prontidão ou meta"),
            )
        else:
            first = max(1, duration // 4)
            second = max(first + 1, duration // 2)
            third = max(second + 1, duration - 1)
            ranges = (
                ("Baseline e técnica", 1, first, "Técnica e consistência"),
                ("Base", first + 1, second, "Construção de volume sustentável"),
                ("Endurance", second + 1, third, "Endurance e especificidade"),
                ("Checkpoint", third + 1, duration, "Teste de prontidão ou meta"),
            )
        return tuple(
            PlanPhase(
                name=name,
                start_week=start,
                end_week=end,
                focus=focus,
                objectives=(focus,),
                success_criteria=("Concluir o estímulo com técnica e esforço controlados",),
            )
            for name, start, end, focus in ranges
            if start <= end
        )

    @staticmethod
    def _session_intents(output_plan: JsonObject) -> tuple[PlanSessionIntent, ...]:
        raw_sessions = output_plan.get("sessions")
        if not isinstance(raw_sessions, list) or not raw_sessions:
            raise DomainError("INTERNAL_ERROR", "Generated week has no sessions.")
        intents: list[PlanSessionIntent] = []
        intensity_by_type = {
            "technique": "EASY",
            "aerobic_endurance": "MODERATE",
            "threshold_css": "HARD",
            "recovery": "EASY",
            "test": "TEST",
        }
        for index, raw in enumerate(raw_sessions, start=1):
            if not isinstance(raw, dict) or not isinstance(raw.get("workout"), dict):
                raise DomainError("INTERNAL_ERROR", "Generated plan session is invalid.")
            purpose = str(raw.get("session_type"))
            intents.append(
                PlanSessionIntent(
                    session_intent_id=str(EntityId.new()),
                    session_number=index,
                    purpose=cast(Any, purpose),
                    target_distance_m=TrainingCycleService._integer(raw.get("distance_m"), 0),
                    max_duration_minutes=TrainingCycleService._integer(
                        raw.get("max_duration_minutes"), 45
                    ),
                    intensity=cast(Any, intensity_by_type.get(purpose, "MODERATE")),
                    scheduled_date=date.fromisoformat(str(raw.get("date"))),
                    key_set=f"Sessão {purpose.replace('_', ' ')} gerada pelo ruleset",
                    workout=cast(JsonObject, raw["workout"]),
                )
            )
        return tuple(intents)

    async def _roll_document(
        self,
        user_id: UserId,
        *,
        actor_id: str,
        plan: TrainingPlan,
        current: TrainingPlanDocument,
        reviewed_week: int,
        decision: PlanDecision,
        correlation_id: CorrelationId,
    ) -> TrainingPlanDocument:
        next_week = reviewed_week + 1
        if next_week > plan.duration_weeks:
            return current.model_copy(
                update={
                    "weeks": tuple(
                        week.model_copy(
                            update={"detail_level": PlanDetailLevel.STRATEGIC, "sessions": ()}
                        )
                        if week.detail_level is PlanDetailLevel.DETAILED
                        else week
                        for week in current.weeks
                    )
                }
            )
        preferences = PlanningPreferences(
            focus=(
                "TECHNIQUE"
                if decision in {PlanDecision.RECOVERY, PlanDecision.REGRESS}
                else "GOAL_PACE"
                if decision in {PlanDecision.PROGRESS, PlanDecision.RETEST}
                else "BALANCED"
            ),
            avoid_high_intensity=decision
            in {
                PlanDecision.RECOVERY,
                PlanDecision.REGRESS,
                PlanDecision.HOLD,
                PlanDecision.PAUSE,
            },
        )
        week_start = plan.start_date + timedelta(days=(next_week - 1) * 7)
        run, _, _ = await self._planning.propose_week(
            user_id,
            actor_id=actor_id,
            week_start=week_start,
            preferences=preferences,
            user_notes_present=False,
            correlation_id=correlation_id,
            create_proposal=False,
        )
        intents = self._session_intents(run.output_plan)
        generated_volume = self._integer(run.output_plan.get("target_volume_m"), 0)
        raw_pool_length = intents[0].workout.get("pool_length_m") if intents else None
        pool_length = self._integer(
            raw_pool_length,
            self._integer(current.baseline_snapshot.get("pool_length_m"), 20),
        )
        weeks: list[PlanWeek] = []
        for week in current.weeks:
            if week.week_number <= reviewed_week:
                weeks.append(
                    week.model_copy(
                        update={"detail_level": PlanDetailLevel.STRATEGIC, "sessions": ()}
                    )
                )
            elif week.week_number == next_week:
                weeks.append(
                    week.model_copy(
                        update={
                            "detail_level": PlanDetailLevel.DETAILED,
                            "target_distance_min_m": (
                                int(generated_volume * 0.92) // pool_length * pool_length
                            ),
                            "target_distance_max_m": generated_volume,
                            "target_duration_min_minutes": len(intents) * 20,
                            "target_duration_max_minutes": sum(
                                item.max_duration_minutes for item in intents
                            ),
                            "session_count": len(intents),
                            "sessions": intents,
                        }
                    )
                )
            elif week.week_number == next_week + 1:
                weeks.append(
                    week.model_copy(
                        update={"detail_level": PlanDetailLevel.OUTLINE, "sessions": ()}
                    )
                )
            else:
                weeks.append(
                    week.model_copy(
                        update={"detail_level": PlanDetailLevel.STRATEGIC, "sessions": ()}
                    )
                )
        return current.model_copy(
            update={
                "weeks": tuple(weeks),
                "ruleset_version": str(
                    run.output_plan.get("ruleset_version") or current.ruleset_version
                ),
                "ruleset_hash": str(run.output_plan.get("ruleset_hash") or current.ruleset_hash),
            }
        )

    @staticmethod
    def _validate_document(start_date: date, document: TrainingPlanDocument) -> None:
        pool_lengths: set[int] = set()
        for week in document.weeks:
            if week.detail_level is not PlanDetailLevel.DETAILED:
                continue
            week_start = start_date + timedelta(days=(week.week_number - 1) * 7)
            week_end = week_start + timedelta(days=6)
            for intent in week.sessions:
                if (
                    intent.scheduled_date is None
                    or not week_start <= intent.scheduled_date <= week_end
                ):
                    raise DomainError(
                        "PLAN_VALIDATION_FAILED",
                        "A detailed session must be scheduled inside its plan week.",
                    )
                definition = CanonicalWorkout.model_validate(intent.workout)
                validation = validate_workout(definition)
                if not validation.valid:
                    raise DomainError(
                        "PLAN_VALIDATION_FAILED",
                        "A detailed session contains an invalid canonical workout.",
                        details={"error_codes": ",".join(item.code for item in validation.errors)},
                    )
                if validation.totals.distance_m != intent.target_distance_m:
                    raise DomainError(
                        "PLAN_VALIDATION_FAILED",
                        "Session intent distance does not match its canonical workout.",
                    )
                pool_lengths.add(definition.pool_length_m)
        if len(pool_lengths) > 1:
            raise DomainError(
                "PLAN_VALIDATION_FAILED",
                "Detailed sessions in one plan revision must use the same pool length.",
            )

    @staticmethod
    def _validate_decision(review: PlanReview, decision: PlanDecision) -> None:
        evidence = review.evidence_snapshot
        pain = evidence.get("pain_signals")
        notes = evidence.get("notes")
        pain_note_present = isinstance(notes, list) and any(
            isinstance(item, dict)
            and item.get("category") == NoteCategory.PAIN.value
            and item.get("importance") in {NoteImportance.MEDIUM.value, NoteImportance.HIGH.value}
            for item in notes
        )
        comparable = evidence.get("comparable_evidence_count")
        if decision is PlanDecision.PROGRESS:
            if (isinstance(pain, list) and pain) or pain_note_present:
                raise DomainError(
                    "PLAN_PROGRESS_BLOCKED_BY_PAIN", "Pain evidence blocks progression."
                )
            if review.confidence_cap is EvidenceConfidence.LOW:
                raise DomainError(
                    "PLAN_PROGRESS_LOW_CONFIDENCE", "Low-quality evidence cannot progress the plan."
                )
            if not isinstance(comparable, int) or comparable < 2:
                raise DomainError(
                    "PLAN_PROGRESS_EVIDENCE_REQUIRED",
                    "Progression requires at least two comparable evidence samples.",
                )

    @staticmethod
    def _validate_candidate(
        before: TrainingPlanDocument,
        after: TrainingPlanDocument,
        *,
        reviewed_week: int,
        bindings: tuple[PlanSessionBinding, ...],
    ) -> None:
        if before.duration_weeks != after.duration_weeks:
            raise DomainError("PLAN_VALIDATION_FAILED", "A revision cannot change cycle duration.")
        for week_number in range(1, reviewed_week + 1):
            before_week = before.weeks[week_number - 1]
            after_week = after.weeks[week_number - 1]
            # Rolling may compact an old detailed week but cannot rewrite its prescription.
            if (
                before_week.detail_level is not PlanDetailLevel.DETAILED
                and before_week != after_week
            ):
                raise DomainError("PLAN_PAST_WEEK_IMMUTABLE", "Past plan weeks cannot change.")
        locked_ids = {str(item.session_intent_id) for item in bindings if item.locked}
        after_ids = {item.session_intent_id for week in after.weeks for item in week.sessions}
        if locked_ids & after_ids:
            # The session remains represented by its binding; it must not be rematerialized.
            raise DomainError("PLAN_SESSION_LOCKED", "A locked session cannot be revised.")
        detailed = next(
            (item for item in after.weeks if item.detail_level is PlanDetailLevel.DETAILED), None
        )
        if detailed is not None:
            previous = before.weeks[detailed.week_number - 1]
            if previous.target_distance_max_m:
                limit = int(previous.target_distance_max_m * 1.08)
                if detailed.target_distance_max_m > limit:
                    raise DomainError(
                        "PLAN_VOLUME_LIMIT_EXCEEDED",
                        "The proposed week exceeds the configured volume progression limit.",
                    )

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

    @staticmethod
    def _integer(value: object, default: int) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float, str)):
            try:
                return int(value)
            except ValueError:
                return default
        return default
