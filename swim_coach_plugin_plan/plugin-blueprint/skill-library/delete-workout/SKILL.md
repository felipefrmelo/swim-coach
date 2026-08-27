---
name: delete-workout
description: Delete a planned Swim Coach workout everywhere. Use for English or Portuguese requests to remove a workout from Swim Coach, its local calendar, and Garmin without deleting recorded activities.
---

# Delete a workout everywhere

Resolve the planned workout with `get_workouts`. If exactly one workout matches,
call `delete_workout` once and rely on the host's destructive-action
confirmation. Do not create a proposal/hash/approval flow. Explain that local
removal is immediate, Garmin cleanup may remain queued, and recorded activities
are never deleted. Completed or activity-matched workouts must remain protected.
