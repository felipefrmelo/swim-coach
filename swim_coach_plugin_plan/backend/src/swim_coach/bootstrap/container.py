"""Composition of P01 application services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from swim_coach.application.services import ContextService, IdentityService, SessionService
from swim_coach.application.services.oidc_login import OidcLoginService
from swim_coach.infrastructure.auth import OidcClient
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.settings import Settings


@dataclass(frozen=True, slots=True)
class AppServices:
    database: Database
    uow_factory: SqlAlchemyUnitOfWorkFactory
    context: ContextService
    identity: IdentityService
    sessions: SessionService
    oidc_login: OidcLoginService | None


def build_services(settings: Settings, database: Database | None = None) -> AppServices:
    database = database or Database(str(settings.database_url))
    uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
    identity = IdentityService(
        uow_factory,
        allowed_emails=settings.allowed_emails,
        allowed_subjects=settings.allowed_subjects,
    )
    sessions = SessionService(
        uow_factory,
        lifetime=timedelta(hours=settings.session_lifetime_hours),
    )
    oidc_login: OidcLoginService | None = None
    if settings.oidc_issuer is not None and settings.oidc_client_id is not None:
        client_secret = (
            settings.oidc_client_secret.get_secret_value()
            if settings.oidc_client_secret is not None
            else None
        )
        oidc_login = OidcLoginService(
            uow_factory=uow_factory,
            oidc_client=OidcClient(
                issuer=str(settings.oidc_issuer),
                client_id=settings.oidc_client_id,
                client_secret=client_secret,
            ),
            identity_service=identity,
            session_service=sessions,
            redirect_uri=settings.oidc_redirect_uri,
        )
    return AppServices(
        database=database,
        uow_factory=uow_factory,
        context=ContextService(uow_factory),
        identity=identity,
        sessions=sessions,
        oidc_login=oidc_login,
    )
