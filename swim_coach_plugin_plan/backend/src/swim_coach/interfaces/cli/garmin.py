"""Secure Garmin connection and one-shot synchronization commands."""

from __future__ import annotations

import argparse
import asyncio
import json
from getpass import getpass

from swim_coach.application.ports.garmin import GarminProviderError
from swim_coach.bootstrap.container import AppServices, build_services
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.value_objects import UserId
from swim_coach.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("connect", "status", "disconnect", "sync-once"):
        command = subparsers.add_parser(name)
        command.add_argument("--user-email", required=True, help="Swim Coach account email")
    return parser.parse_args()


async def _user_id(services: AppServices, email: str) -> UserId:
    async with services.uow_factory() as uow:
        user = await uow.users.get_by_email(email)
    if user is None:
        raise DomainError("USER_NOT_FOUND", "The Swim Coach user was not found.")
    return user.id


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    services = build_services(settings)
    try:
        if services.garmin_connection is None or services.garmin_sync is None:
            raise DomainError(
                "GARMIN_NOT_CONFIGURED",
                "Configure SWIM_COACH_GARMIN_MASTER_KEYS and its active version.",
            )
        user_id = await _user_id(services, args.user_email)
        if args.command == "connect":
            garmin_email = getpass("Garmin email (input hidden): ")
            garmin_password = getpass("Garmin password (input hidden): ")
            try:
                connection = await services.garmin_connection.connect(
                    user_id,
                    email=garmin_email,
                    password=garmin_password,
                    prompt_mfa=lambda: getpass("Garmin MFA code (input hidden): "),
                )
            finally:
                garmin_password = ""
                garmin_email = ""
            output = {
                "garmin_connection": "connected",
                "account_label_masked": connection.account_label_masked,
                "secret_storage": "aes-256-gcm",
                "password_stored": False,
            }
        elif args.command == "status":
            status_connection = await services.garmin_connection.status(user_id)
            output = {
                "status": (
                    status_connection.status.value if status_connection else "not_connected"
                ),
                "account_label_masked": (
                    status_connection.account_label_masked if status_connection else "***"
                ),
                "last_success_at": (
                    status_connection.last_success_at.isoformat()
                    if status_connection and status_connection.last_success_at
                    else None
                ),
                "last_error_code": (
                    status_connection.last_error_code if status_connection else None
                ),
            }
        elif args.command == "disconnect":
            disconnected = await services.garmin_connection.disconnect(user_id)
            output = {
                "status": disconnected.status.value,
                "local_token_revoked": disconnected.encrypted_token is None,
            }
        else:
            sync_run = await services.garmin_sync.sync(user_id, trigger="cli")
            output = {
                "sync_run_id": str(sync_run.id),
                "status": sync_run.status.value,
                "listed": sync_run.listed,
                "created": sync_run.created,
                "updated": sync_run.updated,
                "skipped": sync_run.skipped,
                "failed": sync_run.failed,
            }
        print(json.dumps(output, sort_keys=True))
        return 0
    finally:
        await services.database.dispose()


def main() -> None:
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except DomainError as exc:
        print(json.dumps({"error": exc.code}, sort_keys=True))
        raise SystemExit(2) from exc
    except GarminProviderError as exc:
        print(json.dumps({"error": exc.category.value, "retryable": exc.retryable}, sort_keys=True))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
