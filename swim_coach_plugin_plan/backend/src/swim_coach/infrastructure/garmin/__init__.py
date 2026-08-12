"""Garmin Connect read-only infrastructure adapter."""

from swim_coach.infrastructure.garmin.bootstrap import GarminConnectBootstrap
from swim_coach.infrastructure.garmin.fake_write import FakeGarminWorkoutProvider
from swim_coach.infrastructure.garmin.provider import GarminConnectProvider

__all__ = ["FakeGarminWorkoutProvider", "GarminConnectBootstrap", "GarminConnectProvider"]
