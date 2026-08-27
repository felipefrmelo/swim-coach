"""Deterministic canonical-workout to Garmin payload compiler."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from swim_coach.application.ports.garmin import (
    GarminWorkoutCapabilities,
    GarminWorkoutDTO,
)
from swim_coach.domain.shared.errors import DomainError
from swim_coach.domain.shared.types import JsonObject
from swim_coach.domain.workouts import RepeatNode, StepNode, WorkoutRevision

_SPORT: JsonObject = {"sportTypeId": 4, "sportTypeKey": "swimming", "displayOrder": 3}
_NO_TARGET: JsonObject = {
    "workoutTargetTypeId": 1,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}
_PACE_TARGET: JsonObject = {
    "workoutTargetTypeId": 6,
    "workoutTargetTypeKey": "pace.zone",
    "displayOrder": 6,
}
_SWIM_INSTRUCTION_TARGET: JsonObject = {
    "workoutTargetTypeId": 18,
    "workoutTargetTypeKey": "swim.instruction",
    "displayOrder": 18,
}
_METER_UNIT: JsonObject = {"unitId": 1, "unitKey": "meter", "factor": 100.0}
_DEFAULT_CAPABILITIES = GarminWorkoutCapabilities(
    supports_pace_target=True,
    supports_rpe_target=True,
)
_STEP_TYPES = {
    "WARMUP": (1, "warmup", 1),
    "COOLDOWN": (2, "cooldown", 2),
    "WORK": (3, "interval", 3),
    "DRILL": (3, "interval", 3),
    "RECOVERY": (4, "recovery", 4),
    "REST": (5, "rest", 5),
    "OTHER": (7, "other", 7),
}
_STROKE_IDS = {
    "freestyle": 1,
    "backstroke": 2,
    "breaststroke": 3,
    "butterfly": 4,
    "mixed": 6,
    "choice": 0,
}


@dataclass(slots=True)
class _CompileState:
    capabilities: GarminWorkoutCapabilities
    warnings: list[str]


class GarminWorkoutCompiler:
    def __init__(self, capabilities: GarminWorkoutCapabilities | None = None) -> None:
        self._capabilities = capabilities or _DEFAULT_CAPABILITIES

    def compile(self, revision: WorkoutRevision) -> GarminWorkoutDTO:
        definition = revision.definition
        if len(definition.nodes) > self._capabilities.max_top_level_steps:
            raise DomainError(
                "GARMIN_WORKOUT_UNSUPPORTED",
                "The workout has more top-level steps than the Garmin capability allows.",
                details={"maximum": self._capabilities.max_top_level_steps},
            )
        state = _CompileState(self._capabilities, [])
        source_revision_hash = hashlib.sha256(
            f"{revision.id}:{revision.content_hash}".encode()
        ).hexdigest()
        steps = [
            self._compile_node(node, order=index, depth=1, state=state)
            for index, node in enumerate(definition.nodes, start=1)
        ]
        payload = cast(
            JsonObject,
            {
                "workoutName": definition.title,
                "description": self._description(revision, source_revision_hash),
                "sportType": _SPORT,
                "estimatedDurationInSecs": round(revision.totals.estimated_total_seconds),
                "estimatedDistanceInMeters": float(revision.totals.distance_m),
                "poolLength": float(definition.pool_length_m),
                "poolLengthUnit": _METER_UNIT,
                "workoutSegments": [
                    {"segmentOrder": 1, "sportType": _SPORT, "workoutSteps": steps}
                ],
            },
        )
        compiled_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        return GarminWorkoutDTO(
            payload=payload,
            compiled_hash=compiled_hash,
            source_revision_hash=source_revision_hash,
            warnings=tuple(dict.fromkeys(state.warnings)),
        )

    def _compile_node(
        self,
        node: StepNode | RepeatNode,
        *,
        order: int,
        depth: int,
        state: _CompileState,
    ) -> JsonObject:
        if isinstance(node, RepeatNode):
            if depth > state.capabilities.max_repeat_depth:
                raise DomainError(
                    "GARMIN_WORKOUT_UNSUPPORTED",
                    "The workout repeat nesting exceeds the Garmin capability.",
                    details={"maximum_depth": state.capabilities.max_repeat_depth},
                )
            children = [
                self._compile_node(child, order=index, depth=depth + 1, state=state)
                for index, child in enumerate(node.children, start=1)
            ]
            return cast(
                JsonObject,
                {
                    "type": "RepeatGroupDTO",
                    "stepOrder": order,
                    "stepType": {
                        "stepTypeId": 6,
                        "stepTypeKey": "repeat",
                        "displayOrder": 6,
                    },
                    "numberOfIterations": node.repetitions,
                    "workoutSteps": children,
                    "endCondition": {
                        "conditionTypeId": 7,
                        "conditionTypeKey": "iterations",
                        "displayOrder": 7,
                        "displayable": False,
                    },
                    "endConditionValue": float(node.repetitions),
                    "smartRepeat": False,
                },
            )
        return self._compile_step(node, order=order, state=state)

    def _compile_step(self, node: StepNode, *, order: int, state: _CompileState) -> JsonObject:
        step_id, step_key, step_display = _STEP_TYPES[node.step_role]
        end = node.end_condition
        value: int | float | None
        if end.type == "distance":
            condition_id, condition_key, condition_display, value = 3, "distance", 3, end.meters
        elif end.type == "time":
            condition_id, condition_key, condition_display, value = 2, "time", 2, end.seconds
        else:
            condition_id, condition_key, condition_display, value = 1, "lap.button", 1, None
        stroke = node.stroke.type
        if stroke == "drill":
            state.warnings.append("DRILL_STROKE_DOWNGRADED_TO_CHOICE")
            stroke = "choice"
        if stroke not in state.capabilities.supported_strokes:
            raise DomainError(
                "GARMIN_WORKOUT_UNSUPPORTED",
                "The workout contains a stroke unsupported by the target device.",
                details={"stroke": stroke},
            )
        if node.equipment and node.equipment != ("NONE",):
            if not state.capabilities.supports_equipment:
                state.warnings.append("EQUIPMENT_OMITTED_FROM_GARMIN_PAYLOAD")
        result: dict[str, object] = {
            "type": "ExecutableStepDTO",
            "stepOrder": order,
            "stepType": {
                "stepTypeId": step_id,
                "stepTypeKey": step_key,
                "displayOrder": step_display,
            },
            "endCondition": {
                "conditionTypeId": condition_id,
                "conditionTypeKey": condition_key,
                "displayOrder": condition_display,
                "displayable": True,
            },
            "targetType": _NO_TARGET,
            "strokeType": {"strokeTypeId": _STROKE_IDS[stroke], "displayOrder": 1},
        }
        if value is not None:
            result["endConditionValue"] = float(value)
        if end.type == "distance":
            result["preferredEndConditionUnit"] = _METER_UNIT
        target_cue = self._compile_target(node, result=result, state=state)
        description = self._step_description(node, target_cue=target_cue)
        if description:
            result["description"] = description
        return cast(JsonObject, result)

    @staticmethod
    def _compile_target(
        node: StepNode,
        *,
        result: dict[str, object],
        state: _CompileState,
    ) -> str | None:
        target = node.target
        if target.type == "none":
            return None
        if target.type == "pace_range":
            if not state.capabilities.supports_pace_target:
                state.warnings.append("PACE_TARGET_DOWNGRADED_TO_TEXT")
                return (
                    "Ritmo "
                    f"{GarminWorkoutCompiler._format_pace(target.min_seconds_per_100m)}-"
                    f"{GarminWorkoutCompiler._format_pace(target.max_seconds_per_100m)}/100 m"
                )
            result.update(
                {
                    "secondaryTargetType": _PACE_TARGET,
                    "secondaryTargetValueOne": 100 / target.max_seconds_per_100m,
                    "secondaryTargetValueTwo": 100 / target.min_seconds_per_100m,
                }
            )
            return None
        if target.type == "rpe":
            if not state.capabilities.supports_rpe_target:
                state.warnings.append("RPE_TARGET_DOWNGRADED_TO_TEXT")
                return f"RPE {target.min}-{target.max}"
            result.update(
                {
                    "secondaryTargetType": _SWIM_INSTRUCTION_TARGET,
                    "secondaryTargetValueOne": float(
                        GarminWorkoutCompiler._garmin_effort(target.min, target.max)
                    ),
                    "secondaryTargetValueTwo": 0.0,
                }
            )
            state.warnings.append("RPE_TARGET_MAPPED_TO_GARMIN_EFFORT_CATEGORY")
            return f"RPE {target.min}-{target.max}"
        # A native named-zone mapping is not implemented yet. Preserve it visibly
        # even when a provider advertises the broader capability instead of
        # silently dropping the athlete's target.
        state.warnings.append("ZONE_TARGET_DOWNGRADED_TO_TEXT")
        return f"Zona {target.zone}"

    @staticmethod
    def _step_description(node: StepNode, *, target_cue: str | None) -> str | None:
        instructions = (
            node.instructions if node.instructions and node.instructions.strip() else None
        )
        if instructions and target_cue:
            return f"{instructions} · {target_cue}"
        return instructions or target_cue

    @staticmethod
    def _garmin_effort(minimum: int, maximum: int) -> int:
        midpoint = (minimum + maximum + 1) // 2
        if midpoint == 1:
            return 1  # recovery
        if midpoint == 2:
            return 2  # very_easy
        if midpoint <= 4:
            return 3  # easy
        if midpoint <= 6:
            return 4  # moderate
        if midpoint <= 8:
            return 5  # hard
        if midpoint == 9:
            return 6  # very_hard
        return 7  # all_out

    @staticmethod
    def _format_pace(seconds: float) -> str:
        rounded = round(seconds)
        minutes, remainder = divmod(rounded, 60)
        return f"{minutes}:{remainder:02d}"

    @staticmethod
    def _description(revision: WorkoutRevision, source_revision_hash: str) -> str:
        description = revision.definition.description or "Criado pelo Swim Coach"
        marker = f"[swim-coach:{source_revision_hash}]"
        return f"{description[: 2_000 - len(marker) - 1]} {marker}"
