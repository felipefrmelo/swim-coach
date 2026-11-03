import json
from pathlib import Path

from swim_coach.domain.activities.checkin import SwimCheckIn
from swim_coach.domain.workouts.calendar import CalendarRequest

ROOT = Path(__file__).resolve().parents[3]


def test_calendar_and_checkin_contracts_use_the_canonical_models() -> None:
    for filename, model in [
        ("calendar-request.schema.json", CalendarRequest),
        ("swim-check-in.schema.json", SwimCheckIn),
    ]:
        assert json.loads((ROOT / "contracts" / filename).read_text()) == model.model_json_schema()
