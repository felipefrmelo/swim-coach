"""A small coaching brief built from execution, response and measurement reliability."""

from typing import Any


def weekly_checkpoint(activities: list[dict[str, Any]]) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    confirmed_complete = 0
    confirmed_partial = 0
    excluded = []
    responses = []
    for activity in activities:
        execution = activity["execution_evidence"]
        check_in = execution.get("check_in") or {}
        confirmation = execution["completion"]
        confirmed_complete += confirmation == "CONFIRMED_COMPLETE"
        confirmed_partial += confirmation == "CONFIRMED_PARTIAL"
        if execution["performance_blocked"]:
            excluded.append(activity["activity_id"])
        if confirmation == "UNCONFIRMED":
            questions.append(
                {
                    "activity_id": activity["activity_id"],
                    "field": "completed_as_planned",
                    "question": "Você concluiu o treino como estava previsto?",
                }
            )
        if check_in.get("watch_data_accurate") is None and (
            activity["data_quality"].get("level") != "HIGH"
        ):
            questions.append(
                {
                    "activity_id": activity["activity_id"],
                    "field": "watch_data_accurate",
                    "question": "O relógio registrou corretamente este treino?",
                }
            )
        responses.append(
            {
                "activity_id": activity["activity_id"],
                "session_evaluation": activity["metrics"].get("session_evaluation"),
                "feedback": activity["feedback"],
                "main_difficulty": check_in.get("main_difficulty"),
            }
        )
    return {
        "execution": {
            "recorded_sessions": len(activities),
            "confirmed_complete_sessions": confirmed_complete,
            "confirmed_partial_sessions": confirmed_partial,
            "unconfirmed_sessions": len(activities) - confirmed_complete - confirmed_partial,
            "note": "An activity match proves attendance, not completion of every prescribed step.",
        },
        "athlete_response": responses,
        "measurement": {
            "excluded_performance_activity_ids": excluded,
            "note": "Confirmation never repairs recorded distance, pace, stroke or training load.",
        },
        "missing_context": questions,
        "coach_task": (
            "Ask only missing context that would change your decision, one question at a time. "
            "Explain the week's execution, effort/technique and trustworthy comparable evidence "
            "separately. Choose whether to maintain, progress or ease future training yourself; "
            "the backend makes no prescription. State what changes and why, a technical focus "
            "and an observable success criterion for the next session. Assess progress to the "
            "goal using comparable sustained blocks, not short-repeat pace extrapolation. "
            "Propose the full future revision for explicit approval; "
            "Garmin publication is separate."
        ),
        "decision": None,
    }


def adaptation_metrics(metrics: dict[str, Any], *, blocked: bool) -> dict[str, Any]:
    """Keep athlete response but withhold disputed performance from the coach's decision input."""
    if not blocked:
        return metrics
    return {
        "session_evaluation": metrics.get("session_evaluation"),
        "sets": [],
        "data_quality": {"level": "LOW", "reasons": ["ATHLETE_REPORTED_WATCH_ERROR"]},
    }
