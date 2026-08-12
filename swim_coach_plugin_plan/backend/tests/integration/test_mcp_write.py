"""P08 authenticated writes, exact-hash approval, dynamic scope and replay safety."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from swim_coach.application.services.mcp_read import MCP_READ_SCOPES, McpPrincipal
from swim_coach.application.services.mcp_write import MCP_WRITE_SCOPES
from swim_coach.bootstrap.container import build_services
from swim_coach.domain.athlete import Device
from swim_coach.domain.operations import Job, JobStatus
from swim_coach.domain.shared import CorrelationId
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import EntityId
from swim_coach.domain.workouts import CanonicalWorkout
from swim_coach.infrastructure.db import Database
from swim_coach.infrastructure.db.models import (
    ActionApprovalModel,
    ActionExecutionModel,
    JobModel,
)
from swim_coach.interfaces.mcp.server import create_mcp_server
from swim_coach.settings import Settings

from .test_workout_authoring import canonical_workout


class WriteTokenVerifier:
    def __init__(self, subjects: dict[str, tuple[str, list[str]]]) -> None:
        self._subjects = subjects

    async def verify_token(self, token: str) -> AccessToken | None:
        resolved = self._subjects.get(token)
        if resolved is None:
            return None
        subject, scopes = resolved
        return AccessToken(
            token="",
            client_id="mcp-write-integration",
            scopes=scopes,
            expires_at=int(datetime.now(UTC).timestamp()) + 300,
            resource="https://swim.example.test/mcp",
            subject=subject,
        )


async def test_mcp_preview_approve_execute_requires_two_boundaries_and_replays_once(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={
            "oauth_issuer": "https://tenant.example.test",
            "oauth_resource": "https://swim.example.test/mcp",
            "mcp_write_enabled": True,
            "garmin_write_enabled": True,
            "garmin_write_mode": "fake",
        }
    )
    services = build_services(settings, database)
    owner = await services.identity.ensure_identity(
        provider="oidc",
        subject="mcp-write-owner",
        email="first@example.test",
        display_name="Owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    await services.identity.ensure_identity(
        provider="oidc",
        subject="mcp-write-other",
        email="second@example.test",
        display_name="Other",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    pools = await services.context.list_pools(owner.id)
    now = datetime.now(UTC)
    async with services.uow_factory() as uow:
        await uow.devices.add(
            Device(
                id=EntityId.new(),
                user_id=owner.id,
                provider="garmin",
                external_device_id="fake-device-p08",
                model="Forerunner test",
                name="Disposable watch",
                is_primary=True,
                capabilities={"workout_write": True},
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await uow.commit()
    workout = await services.workouts.create_draft(
        owner.id,
        CanonicalWorkout.model_validate(canonical_workout()),
        pool_id=pools[0].id,
        correlation_id=CorrelationId.new(),
    )
    workout = await services.workouts.approve_local(
        owner.id,
        workout.workout.id,
        expected_version=workout.workout.version,
        expected_content_hash=workout.current_revision.content_hash,
        correlation_id=CorrelationId.new(),
    )
    today = datetime.now(UTC).date()
    workout = await services.workouts.schedule(
        owner.id,
        workout.workout.id,
        scheduled_date=today,
        scheduled_start_time=None,
        timezone="America/Sao_Paulo",
        pool_id=pools[0].id,
        expected_version=workout.workout.version,
        correlation_id=CorrelationId.new(),
    )

    full_scopes = list((*MCP_READ_SCOPES, *MCP_WRITE_SCOPES))
    verifier = WriteTokenVerifier(
        {
            "full": ("mcp-write-owner", full_scopes),
            "no-garmin": (
                "mcp-write-owner",
                [scope for scope in full_scopes if scope != "garmin:publish"],
            ),
            "other": ("mcp-write-other", full_scopes),
        }
    )
    assert services.mcp_write is not None
    server = create_mcp_server(
        read_service=services.mcp_read,
        write_service=services.mcp_write,
        token_verifier=verifier,
        oauth_issuer="https://tenant.example.test",
        oauth_resource="https://swim.example.test/mcp",
    )
    app = server.streamable_http_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer full"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    preview = await session.call_tool(
                        "preview_garmin_publish",
                        {
                            "workout_id": str(workout.workout.id),
                            "revision": workout.current_revision.revision_number,
                            "schedule_date": today.isoformat(),
                            "idempotency_key": "preview-p08-0001",
                        },
                    )
                    assert preview.isError is False
                    proposal = preview.structuredContent["data"]
                    assert proposal["status"] == "READY_FOR_REVIEW"
                    assert proposal["execution"] is None

                    premature = await session.call_tool(
                        "execute_approved_action",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "idempotency_key": "execute-p08-0001",
                        },
                    )
                    assert premature.isError is True
                    assert "ACTION_STATE_CONFLICT" in premature.content[0].text

                    tampered = await session.call_tool(
                        "approve_action_proposal",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "expected_action_hash": "0" * 64,
                            "decision": "APPROVE",
                            "confirmation_text": "Confirmo a publicação exibida.",
                        },
                    )
                    assert tampered.isError is True
                    assert "ACTION_TAMPERED" in tampered.content[0].text

                    approved = await session.call_tool(
                        "approve_action_proposal",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "expected_action_hash": proposal["action_hash"],
                            "decision": "APPROVE",
                            "confirmation_text": "Confirmo a publicação exibida.",
                        },
                    )
                    assert approved.isError is False
                    assert approved.structuredContent["data"]["status"] == "APPROVED"
                    assert approved.structuredContent["data"]["execution"] is None

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer no-garmin"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    missing_dynamic_scope = await session.call_tool(
                        "execute_approved_action",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "idempotency_key": "execute-p08-0001",
                        },
                    )
                    assert missing_dynamic_scope.isError is True
                    assert "SCOPE_REQUIRED" in missing_dynamic_scope.content[0].text

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer other"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    idor = await session.call_tool(
                        "get_action_proposal", {"proposal_id": proposal["proposal_id"]}
                    )
                    assert idor.isError is True
                    assert "RESOURCE_NOT_FOUND" in idor.content[0].text

        principal = McpPrincipal(owner.id, "mcp-write-owner", frozenset(full_scopes))
        executed_direct, concurrent_replay = await asyncio.gather(
            services.mcp_write.execute_approved_action(
                principal,
                "execute-direct-1",
                proposal_id=EntityId.parse(proposal["proposal_id"]),
                idempotency_key="execute-p08-0001",
                correlation_id=CorrelationId.new(),
            ),
            services.mcp_write.execute_approved_action(
                principal,
                "execute-direct-2",
                proposal_id=EntityId.parse(proposal["proposal_id"]),
                idempotency_key="execute-p08-concurrent-key",
                correlation_id=CorrelationId.new(),
            ),
        )
        assert (
            executed_direct.data["execution"]["execution_id"]
            == concurrent_replay.data["execution"]["execution_id"]
        )

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
            headers={"Authorization": "Bearer full"},
        ) as client:
            async with streamable_http_client("http://127.0.0.1/", http_client=client) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    replay = await session.call_tool(
                        "execute_approved_action",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "idempotency_key": "execute-p08-replay-different-key",
                        },
                    )
                    assert replay.isError is False
                    assert replay.structuredContent["data"]["status"] == "QUEUED"
                    assert (
                        replay.structuredContent["data"]["execution"]["execution_id"]
                        == executed_direct.data["execution"]["execution_id"]
                    )
                    assert (
                        replay.structuredContent["data"]["job_id"] == executed_direct.data["job_id"]
                    )

    async with database.session_factory() as session:
        approval_count = await session.scalar(select(func.count()).select_from(ActionApprovalModel))
        approval_verb = await session.scalar(select(ActionApprovalModel.explicit_verb))
        execution_count = await session.scalar(
            select(func.count()).select_from(ActionExecutionModel)
        )
        publish_job_count = await session.scalar(
            select(func.count())
            .select_from(JobModel)
            .where(JobModel.job_type == "workout.publish_garmin")
        )
    assert approval_count == 1
    assert approval_verb == "Confirmo a publicação exibida."
    assert execution_count == 1
    assert publish_job_count == 1


async def test_safe_failed_job_retry_is_atomic_idempotent_and_rejects_ambiguity(
    database: Database, app_settings: Settings
) -> None:
    settings = app_settings.model_copy(
        update={
            "oauth_issuer": "https://tenant.example.test",
            "oauth_resource": "https://swim.example.test/mcp",
            "mcp_write_enabled": True,
        }
    )
    services = build_services(settings, database)
    user = await services.identity.ensure_identity(
        provider="oidc",
        subject="mcp-retry-owner",
        email="first@example.test",
        display_name="Owner",
        claims_snapshot={"email_verified": True},
        correlation_id=CorrelationId.new(),
    )
    safe_job = Job(
        id=EntityId.new(),
        user_id=user.id,
        job_type="garmin.sync_activities",
        payload={"user_id": str(user.id)},
        status=JobStatus.FAILED_TERMINAL,
        attempts=1,
        last_error={"code": "RATE_LIMITED", "retryable": True},
        finished_at=datetime.now(UTC),
    )
    ambiguous_job = Job(
        id=EntityId.new(),
        user_id=user.id,
        job_type="workout.publish_garmin",
        payload={"proposal_id": str(EntityId.new())},
        status=JobStatus.FAILED_TERMINAL,
        attempts=1,
        last_error={
            "code": "PROVIDER_TIMEOUT",
            "retryable": True,
            "ambiguous_external_effect": True,
        },
        finished_at=datetime.now(UTC),
    )
    async with services.uow_factory() as uow:
        await uow.jobs.add(safe_job)
        await uow.jobs.add(ambiguous_job)
        await uow.commit()

    assert services.mcp_write is not None
    principal = McpPrincipal(user.id, "mcp-retry-owner", frozenset({"operations:retry"}))
    first = await services.mcp_write.retry_failed_job(
        principal,
        "retry-first",
        job_id=safe_job.id,
        idempotency_key="retry-safe-0001",
        correlation_id=CorrelationId.new(),
    )
    replay = await services.mcp_write.retry_failed_job(
        principal,
        "retry-replay",
        job_id=safe_job.id,
        idempotency_key="retry-safe-0001",
        correlation_id=CorrelationId.new(),
    )
    assert first.data["status"] == JobStatus.RETRY_SCHEDULED.value
    assert first.data["replayed"] is False
    assert replay.data["replayed"] is True

    with pytest.raises(DomainError) as captured:
        await services.mcp_write.retry_failed_job(
            principal,
            "retry-ambiguous",
            job_id=ambiguous_job.id,
            idempotency_key="retry-ambiguous-0001",
            correlation_id=CorrelationId.new(),
        )
    assert getattr(captured.value, "code", None) == "JOB_NOT_RETRYABLE"
