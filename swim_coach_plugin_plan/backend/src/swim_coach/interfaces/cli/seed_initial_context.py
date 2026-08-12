"""Idempotently create the initial 20 m / 2 km context for one allowlisted user."""

from __future__ import annotations

import argparse
import asyncio
import json

from swim_coach.application.services.identity import IdentityService
from swim_coach.domain.shared.value_objects import CorrelationId
from swim_coach.infrastructure.db import Database, SqlAlchemyUnitOfWorkFactory
from swim_coach.settings import get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Allowlisted local account email")
    parser.add_argument("--display-name", default="Nadador", help="Local display name")
    return parser.parse_args()


async def seed(email: str, display_name: str) -> None:
    settings = get_settings()
    database = Database(str(settings.database_url))
    try:
        uow_factory = SqlAlchemyUnitOfWorkFactory(database.session_factory)
        service = IdentityService(
            uow_factory,
            allowed_emails=frozenset({email.casefold()}),
            allowed_subjects=frozenset(),
        )
        user = await service.ensure_identity(
            provider="seed",
            subject=f"seed:{email.casefold()}",
            email=email,
            display_name=display_name,
            claims_snapshot={"seed": True},
            correlation_id=CorrelationId.new(),
        )
        async with uow_factory() as uow:
            pools = await uow.pools.list(user.id)
            goals = await uow.goals.list(user.id)
        default_pool = next(pool for pool in pools if pool.is_default)
        initial_goal = next(goal for goal in goals if goal.title == "Nadar 2.000 m em 45 min")
        print(
            json.dumps(
                {
                    "initial_context_seed": "passed",
                    "pool_length_m": default_pool.length.meters,
                    "target_distance_m": initial_goal.target_distance.meters,
                    "target_duration_seconds": int(initial_goal.target_duration.seconds),
                    "target_pace_seconds_per_100m": int(initial_goal.target_pace.seconds_per_100m),
                },
                sort_keys=True,
            )
        )
    finally:
        await database.dispose()


def main() -> None:
    args = parse_args()
    asyncio.run(seed(args.email, args.display_name))


if __name__ == "__main__":
    main()
