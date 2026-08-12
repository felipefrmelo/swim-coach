"""Run a read-only Garmin feasibility probe with sanitized output."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from getpass import getpass
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from garminconnect.workout import (
    SwimmingWorkout,
    WorkoutSegment,
    create_distance_interval_step,
)


def build_local_swimming_model() -> tuple[SwimmingWorkout, str]:
    """Build and validate a 20 m swimming model without uploading it."""

    sport_type = {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3}
    workout = SwimmingWorkout(
        workoutName="Swim Coach P00 local model",
        estimatedDurationInSecs=27,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType=sport_type,
                workoutSteps=[create_distance_interval_step(20.0, step_order=1)],
            )
        ],
    )
    canonical = json.dumps(workout.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return workout, hashlib.sha256(canonical.encode()).hexdigest()


def is_pool_swim(activity: dict[str, Any]) -> bool:
    activity_type = activity.get("activityType")
    if not isinstance(activity_type, dict):
        return False
    key = activity_type.get("typeKey")
    return isinstance(key, str) and key in {"lap_swimming", "pool_swimming"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--token-store",
        type=Path,
        default=Path(".local/garmin-spike"),
        help="Ignored owner-only temporary token directory",
    )
    parser.add_argument(
        "--keep-token-store",
        action="store_true",
        help="Keep the temporary token store for a controlled follow-up probe",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token_store = args.token_store.resolve()
    token_store.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_store.chmod(0o700)

    email = getpass("Garmin email (input hidden): ")
    password = getpass("Garmin password (input hidden): ")
    client = Garmin(email, password, prompt_mfa=lambda: getpass("Garmin MFA code: "))

    try:
        client.login(str(token_store))
        activities = client.get_activities(0, 20)
        devices = client.get_devices()
        _, model_sha256 = build_local_swimming_model()
        target_device_detected = any(
            "forerunner 265" in str(device.get("displayName", "")).lower()
            for device in devices
            if isinstance(device, dict)
        )
        sanitized = {
            "garmin_read_probe": "passed",
            "recent_activity_count": len(activities),
            "recent_pool_swim_count": sum(
                is_pool_swim(activity) for activity in activities if isinstance(activity, dict)
            ),
            "device_count": len(devices),
            "target_device_family_detected": target_device_detected,
            "local_swimming_model_valid": True,
            "local_swimming_model_sha256": model_sha256,
            "external_write_performed": False,
        }
        print(json.dumps(sanitized, sort_keys=True))
    finally:
        password = ""
        email = ""
        if not args.keep_token_store:
            shutil.rmtree(token_store, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
