"""Bounded schema recovery details with paths, without echoing submitted data."""

from collections.abc import Sequence
from typing import Any


def schema_recovery(errors: Sequence[Any], payload: Any = None) -> dict[str, Any]:
    issues = [
        {
            "path": ".".join(str(p) for p in e["loc"]),
            "code": e["type"],
            "repair_action": "CORRECT_FIELD",
            "repair_hint": "Use the canonical input schema for this field.",
        }
        for e in errors[:20]
    ]

    def walk(value: Any, path: str) -> None:
        if len(issues) >= 24:
            return
        if isinstance(value, dict):
            if "role" in value:
                issues.append(
                    {
                        "path": f"{path}.role",
                        "code": "UNKNOWN_STEP_ROLE_FIELD",
                        "repair_action": "RENAME_FIELD",
                        "repair_hint": "Use step_role: WORK (or WARMUP, REST, DRILL, COOLDOWN).",
                    }
                )
            if value.get("max_duration_minutes") is not None and "session_number" in value:
                issues.append(
                    {
                        "path": f"{path}.max_duration_minutes",
                        "code": "LEGACY_DURATION_FIELD",
                        "repair_action": "REMOVE_LEGACY_FIELD",
                        "repair_hint": "For COACH_DEFINED use planned_duration_minutes; "
                        "omit max_duration_minutes or set null.",
                    }
                )
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(payload, "")
    return {
        "issues": issues,
        "recovery": {
            "next_tool": "get_coach_context",
            "max_automatic_retries": 1,
            "instructions": [
                "Reload context, correct only reported fields and validate again. "
                "Obtain approval before applying a plan proposal."
            ],
        },
    }
