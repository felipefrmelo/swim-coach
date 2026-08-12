"""Garmin Connect read-only infrastructure adapter."""

from swim_coach.infrastructure.garmin.bootstrap import GarminConnectBootstrap
from swim_coach.infrastructure.garmin.provider import GarminConnectProvider

__all__ = ["GarminConnectBootstrap", "GarminConnectProvider"]
