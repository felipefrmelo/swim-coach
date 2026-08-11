---
name: adapt-workout
description: Propose a safe, structured change or reschedule when the user has less time, different availability, fatigue, or wants to preserve a specific workout objective.
---

# Adapt a workout

1. Resolve the workout with `get_today_workout` or `get_week_plan`.
2. Translate the request into explicit constraints: available duration, date, objectives to preserve, intensity limits, and reason.
3. Use `propose_workout_change` for content or `propose_workout_reschedule` for date/time.
4. Explain before versus after, distance/time/load changes, and what was preserved.
5. Do not mutate a published revision in place.
6. Do not approve or execute without an explicit subsequent confirmation workflow.
