"""Athlete-reported execution, distinct from measured performance."""

from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from swim_coach.domain.shared.types import JsonObject


class SwimCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    completed_as_planned: bool | None = None
    watch_data_accurate: bool | None = None
    all_freestyle: bool | None = None
    main_difficulty: str | None = Field(default=None, max_length=500)

    def as_json(self) -> JsonObject:
        return cast(JsonObject, self.model_dump(mode="json"))

    def as_patch(self) -> JsonObject:
        return cast(JsonObject, self.model_dump(mode="json", exclude_unset=True))

    @property
    def has_answers(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


def execution_evidence(check_in: SwimCheckIn | None) -> JsonObject:
    """Do not infer completion, distance, stroke corrections or load from a faulty watch."""
    completed = check_in.completed_as_planned if check_in else None
    disputed = check_in is not None and check_in.watch_data_accurate is False
    return {
        "source": "ATHLETE" if check_in and check_in.has_answers else None,
        "check_in": check_in.as_json() if check_in else None,
        "completion": (
            "CONFIRMED_COMPLETE"
            if completed is True
            else "CONFIRMED_PARTIAL"
            if completed is False
            else "UNCONFIRMED"
        ),
        "performance_blocked": disputed,
        "performance_block_reason": "ATHLETE_REPORTED_WATCH_ERROR" if disputed else None,
        "guidance": (
            "Use execution and effort feedback; do not use recorded pace, stroke, continuity "
            "or distance adherence to adapt training. Do not reconstruct pace or training load."
            if disputed
            else "Measured performance still requires data-quality and comparable-set checks."
        ),
    }
