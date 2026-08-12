"""Garmin connection and read-sync domain records."""

from swim_coach.domain.garmin.entities import (
    Activity,
    ActivityImport,
    ActivityImportStatus,
    GarminConnection,
    GarminConnectionStatus,
    RawProviderPayload,
    SyncCursor,
    SyncRun,
    SyncRunStatus,
)

__all__ = [
    "Activity",
    "ActivityImport",
    "ActivityImportStatus",
    "GarminConnection",
    "GarminConnectionStatus",
    "RawProviderPayload",
    "SyncCursor",
    "SyncRun",
    "SyncRunStatus",
]
