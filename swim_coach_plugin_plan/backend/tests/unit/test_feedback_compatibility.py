from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from swim_coach.application.ports.repositories import UnitOfWorkFactory
from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.garmin_publish import GarminPublishService
from swim_coach.application.services.mcp_read import McpPrincipal
from swim_coach.application.services.mcp_write import McpWriteService
from swim_coach.application.services.sessions import AuthenticatedSession
from swim_coach.application.services.workouts import WorkoutService
from swim_coach.bootstrap.container import AppServices
from swim_coach.domain.activities import SessionFeedback
from swim_coach.domain.shared import CorrelationId, EntityId, UserId
from swim_coach.interfaces.rest.activities import FeedbackRequest, put_feedback
from swim_coach.interfaces.rest.activities_v2 import FeedbackRequestV2, put_feedback_v2


class _RecordingActivityData:
    def __init__(self, feedback: SessionFeedback) -> None:
        self.feedback = feedback
        self.calls: list[dict[str, Any]] = []

    async def record_feedback(self, *_: object, **kwargs: Any) -> SessionFeedback:
        self.calls.append(kwargs)
        return self.feedback


def _feedback() -> SessionFeedback:
    user_id = UserId.new()
    return SessionFeedback(
        id=EntityId.new(),
        user_id=user_id,
        activity_id=EntityId.new(),
        rpe=5,
        feeling_score=72,
    )


@pytest.mark.asyncio
async def test_rest_v1_preserves_unknown_feeling_while_v2_replaces_it() -> None:
    feedback = _feedback()
    activity_data = _RecordingActivityData(feedback)
    services = cast(AppServices, SimpleNamespace(activity_data=activity_data))
    authenticated = cast(
        AuthenticatedSession,
        SimpleNamespace(user=SimpleNamespace(id=feedback.user_id)),
    )

    legacy = await put_feedback(
        feedback.activity_id.value,
        FeedbackRequest(rpe=6, technique_rating=4),
        "legacy-feedback-key",
        authenticated,
        services,
        CorrelationId.new(),
    )
    current = await put_feedback_v2(
        feedback.activity_id.value,
        FeedbackRequestV2(rpe=6, technique_rating=4),
        "current-feedback-key",
        authenticated,
        services,
        CorrelationId.new(),
    )

    assert legacy.rpe == 5
    assert current is not None
    assert activity_data.calls[0]["preserve_existing_feeling_score"] is True
    assert activity_data.calls[1]["preserve_existing_feeling_score"] is False


@pytest.mark.asyncio
async def test_mcp_legacy_defaults_to_preserving_feeling_and_v2_opts_out() -> None:
    feedback = _feedback()
    activity_data = _RecordingActivityData(feedback)
    service = McpWriteService(
        uow_factory=cast(UnitOfWorkFactory, object()),
        workouts=cast(WorkoutService, object()),
        activity_data=cast(ActivityDataService, activity_data),
        garmin_sync=None,
        garmin_publish=cast(GarminPublishService, object()),
    )
    principal = McpPrincipal(feedback.user_id, "fixture", frozenset({"feedback:write"}))

    await service.record_session_feedback(
        principal,
        "legacy-request",
        activity_id=feedback.activity_id,
        rpe=6,
        technique="good",
        pain={"present": False},
        notes=None,
        idempotency_key="legacy-feedback-key",
        correlation_id=CorrelationId.new(),
    )
    await service.record_session_feedback(
        principal,
        "v2-request",
        activity_id=feedback.activity_id,
        rpe=6,
        technique="good",
        pain={"present": False},
        notes=None,
        idempotency_key="v2-feedback-key",
        correlation_id=CorrelationId.new(),
        preserve_existing_feeling_score=False,
    )

    assert activity_data.calls[0]["preserve_existing_feeling_score"] is True
    assert activity_data.calls[1]["preserve_existing_feeling_score"] is False
