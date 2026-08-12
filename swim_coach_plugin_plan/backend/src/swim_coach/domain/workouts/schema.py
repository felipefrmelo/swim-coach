"""Provider-neutral canonical workout schema and deterministic validation."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DistanceEnd(CanonicalModel):
    type: Literal["distance"] = "distance"
    meters: int = Field(ge=1, le=50_000)


class TimeEnd(CanonicalModel):
    type: Literal["time"] = "time"
    seconds: float = Field(gt=0, le=86_400)


class LapButtonEnd(CanonicalModel):
    type: Literal["lap_button"] = "lap_button"


EndCondition = Annotated[DistanceEnd | TimeEnd | LapButtonEnd, Field(discriminator="type")]


class NoTarget(CanonicalModel):
    type: Literal["none"] = "none"


class PaceTarget(CanonicalModel):
    type: Literal["pace_range"] = "pace_range"
    min_seconds_per_100m: float = Field(gt=0)
    max_seconds_per_100m: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_range(self) -> PaceTarget:
        if self.min_seconds_per_100m > self.max_seconds_per_100m:
            raise ValueError("minimum pace must not exceed maximum pace")
        return self


class RpeTarget(CanonicalModel):
    type: Literal["rpe"] = "rpe"
    min: int = Field(ge=1, le=10)
    max: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def validate_range(self) -> RpeTarget:
        if self.min > self.max:
            raise ValueError("minimum RPE must not exceed maximum RPE")
        return self


class ZoneTarget(CanonicalModel):
    type: Literal["zone"] = "zone"
    zone: str = Field(min_length=1, max_length=40)


Target = Annotated[NoTarget | PaceTarget | RpeTarget | ZoneTarget, Field(discriminator="type")]


class StandardStroke(CanonicalModel):
    type: Literal["freestyle", "backstroke", "breaststroke", "butterfly", "mixed", "choice", "kick"]


class DrillStroke(CanonicalModel):
    type: Literal["drill"] = "drill"
    drill: str = Field(min_length=1, max_length=80)
    side: Literal["LEFT", "RIGHT", "ALTERNATE"] | None = None


Stroke = Annotated[StandardStroke | DrillStroke, Field(discriminator="type")]


class StepNode(CanonicalModel):
    type: Literal["step"] = "step"
    id: str | None = Field(default=None, min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=160)
    step_role: Literal["WARMUP", "WORK", "RECOVERY", "REST", "COOLDOWN", "DRILL", "OTHER"] = "WORK"
    end_condition: EndCondition
    target: Target = Field(default_factory=NoTarget)
    stroke: Stroke = Field(default_factory=lambda: StandardStroke(type="freestyle"))
    intensity: Literal["EASY", "MODERATE", "TEMPO", "THRESHOLD", "FAST", "MAX", "CUSTOM"] | None = (
        None
    )
    equipment: tuple[Literal["BOARD", "FINS", "PADDLES", "PULL_BUOY", "SNORKEL", "NONE"], ...] = ()
    instructions: str | None = Field(default=None, max_length=600)

    @model_validator(mode="after")
    def validate_step(self) -> StepNode:
        if len(set(self.equipment)) != len(self.equipment):
            raise ValueError("equipment entries must be unique")
        if "NONE" in self.equipment and len(self.equipment) > 1:
            raise ValueError("NONE cannot be combined with equipment")
        if self.step_role == "REST" and self.end_condition.type == "distance":
            raise ValueError("rest steps cannot use a distance end condition")
        return self


class RepeatNode(CanonicalModel):
    type: Literal["repeat"] = "repeat"
    id: str | None = Field(default=None, min_length=1, max_length=80)
    label: str | None = Field(default=None, max_length=160)
    repetitions: int = Field(ge=1, le=100)
    children: tuple[WorkoutNode, ...] = Field(min_length=1, max_length=50)


WorkoutNode = Annotated[StepNode | RepeatNode, Field(discriminator="type")]
RepeatNode.model_rebuild()


class CanonicalWorkout(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2_000)
    sport: Literal["POOL_SWIMMING"] = "POOL_SWIMMING"
    pool_length_m: int = Field(ge=1, le=200)
    purpose: Literal[
        "TECHNIQUE", "BASE", "ENDURANCE", "THRESHOLD", "SPEED", "RECOVERY", "TEST", "MIXED"
    ]
    tags: tuple[str, ...] = ()
    nodes: tuple[WorkoutNode, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_tags(self) -> CanonicalWorkout:
        if len(set(self.tags)) != len(self.tags):
            raise ValueError("tags must be unique")
        if any(not tag or len(tag) > 40 for tag in self.tags):
            raise ValueError("tags must contain 1 to 40 characters")
        return self


class WorkoutTotals(CanonicalModel):
    distance_m: int
    distance_steps: int
    executable_steps: int
    lengths: int
    active_seconds: float
    rest_seconds: float
    estimated_total_seconds: float


class ValidationIssue(CanonicalModel):
    code: str
    path: str
    message: str


class WorkoutValidationResult(CanonicalModel):
    valid: bool
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]
    totals: WorkoutTotals


def canonical_content_hash(definition: CanonicalWorkout) -> str:
    payload = json.dumps(
        definition.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def validate_workout(
    definition: CanonicalWorkout,
    *,
    max_depth: int = 4,
    max_expanded_steps: int = 1_000,
) -> WorkoutValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    distance_m = distance_steps = executable_steps = lengths = 0
    active_seconds = rest_seconds = 0.0
    seen_ids: set[str] = set()
    roles: set[str] = set()

    def walk(nodes: tuple[WorkoutNode, ...], path: str, multiplier: int, depth: int) -> None:
        nonlocal distance_m, distance_steps, executable_steps, lengths
        nonlocal active_seconds, rest_seconds
        if depth > max_depth:
            errors.append(
                ValidationIssue(
                    code="MAX_DEPTH_EXCEEDED",
                    path=path,
                    message=f"Máximo de {max_depth} níveis de repetição.",
                )
            )
            return
        for index, node in enumerate(nodes):
            node_path = f"{path}/{index}"
            if node.id:
                if node.id in seen_ids:
                    errors.append(
                        ValidationIssue(
                            code="DUPLICATE_NODE_ID",
                            path=f"{node_path}/id",
                            message="O identificador do bloco deve ser único.",
                        )
                    )
                seen_ids.add(node.id)
            if isinstance(node, RepeatNode):
                walk(
                    node.children, f"{node_path}/children", multiplier * node.repetitions, depth + 1
                )
                continue
            executable_steps += multiplier
            roles.add(node.step_role)
            end = node.end_condition
            if isinstance(end, DistanceEnd):
                distance_steps += multiplier
                distance_m += end.meters * multiplier
                if end.meters % definition.pool_length_m:
                    errors.append(
                        ValidationIssue(
                            code="POOL_DISTANCE_MISMATCH",
                            path=f"{node_path}/end_condition/meters",
                            message=(
                                f"Use um múltiplo de {definition.pool_length_m} m "
                                "para terminar na parede."
                            ),
                        )
                    )
                else:
                    lengths += (end.meters // definition.pool_length_m) * multiplier
                if isinstance(node.target, PaceTarget):
                    active_seconds += (
                        end.meters
                        / 100
                        * (
                            (node.target.min_seconds_per_100m + node.target.max_seconds_per_100m)
                            / 2
                        )
                        * multiplier
                    )
            elif isinstance(end, TimeEnd):
                if node.step_role == "REST":
                    rest_seconds += end.seconds * multiplier
                else:
                    active_seconds += end.seconds * multiplier

    walk(definition.nodes, "/nodes", 1, 1)
    if executable_steps > max_expanded_steps:
        errors.append(
            ValidationIssue(
                code="MAX_EXPANDED_STEPS_EXCEEDED",
                path="/nodes",
                message=(
                    f"O treino expande para {executable_steps} etapas; máximo {max_expanded_steps}."
                ),
            )
        )
    if definition.purpose in {"THRESHOLD", "SPEED", "TEST"}:
        if "WARMUP" not in roles:
            warnings.append(
                ValidationIssue(
                    code="WARMUP_RECOMMENDED",
                    path="/nodes",
                    message="Inclua aquecimento antes de uma sessão intensa.",
                )
            )
        if "COOLDOWN" not in roles:
            warnings.append(
                ValidationIssue(
                    code="COOLDOWN_RECOMMENDED",
                    path="/nodes",
                    message="Inclua soltura após uma sessão intensa.",
                )
            )
    totals = WorkoutTotals(
        distance_m=distance_m,
        distance_steps=distance_steps,
        executable_steps=executable_steps,
        lengths=lengths,
        active_seconds=round(active_seconds, 3),
        rest_seconds=round(rest_seconds, 3),
        estimated_total_seconds=round(active_seconds + rest_seconds, 3),
    )
    return WorkoutValidationResult(
        valid=not errors, errors=tuple(errors), warnings=tuple(warnings), totals=totals
    )
