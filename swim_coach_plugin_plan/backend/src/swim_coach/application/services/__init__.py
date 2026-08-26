"""Application services coordinating domain and persistence ports."""

from swim_coach.application.services.activity_data import ActivityDataService
from swim_coach.application.services.automation import AutomationService
from swim_coach.application.services.coach_commands import CoachCommandService
from swim_coach.application.services.context import ContextService
from swim_coach.application.services.garmin_connection import GarminConnectionService
from swim_coach.application.services.garmin_publish import GarminPublishService
from swim_coach.application.services.garmin_sync import GarminSyncService
from swim_coach.application.services.garmin_upsert import GarminUpsertService
from swim_coach.application.services.identity import IdentityService
from swim_coach.application.services.mcp_read import McpReadService
from swim_coach.application.services.mcp_write import McpWriteService
from swim_coach.application.services.planning import PlanningService
from swim_coach.application.services.privacy import PrivacyService
from swim_coach.application.services.sessions import SessionService
from swim_coach.application.services.workouts import WorkoutService

__all__ = [
    "ActivityDataService",
    "AutomationService",
    "CoachCommandService",
    "ContextService",
    "GarminConnectionService",
    "GarminPublishService",
    "GarminSyncService",
    "GarminUpsertService",
    "IdentityService",
    "McpReadService",
    "McpWriteService",
    "PlanningService",
    "PrivacyService",
    "SessionService",
    "WorkoutService",
]
