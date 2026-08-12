import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "probe_garmin_read.py"
SPEC = importlib.util.spec_from_file_location("probe_garmin_read", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_local_swimming_model_is_20m_and_deterministic() -> None:
    workout, first_hash = probe.build_local_swimming_model()
    _, second_hash = probe.build_local_swimming_model()

    step = workout.workoutSegments[0].workoutSteps[0]
    assert step.endConditionValue == 20.0
    assert workout.sportType["sportTypeKey"] == "swimming"
    assert first_hash == second_hash
