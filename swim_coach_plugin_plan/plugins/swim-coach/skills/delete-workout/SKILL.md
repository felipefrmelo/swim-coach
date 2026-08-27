---
name: delete-workout
description: Delete a planned Swim Coach workout everywhere. Use for English or Portuguese requests to remove or exclude a workout from Swim Coach, its local calendar, and Garmin without deleting recorded activities.
---

# Delete a workout everywhere

1. Resolve the intended planned workout with `get_workouts` using the supplied
   ID, date, or week. Ask one short question only when multiple workouts match.
2. Explain briefly that deletion removes the planned workout from Swim Coach,
   the local calendar, the Garmin calendar, and the Garmin workout library.
   Recorded swim activities are never deleted.
3. Call `delete_workout` once. Rely on the host's destructive-action
   confirmation; do not add a proposal, hash, approval, or second confirmation.
4. Report that local removal is immediate and Garmin cleanup may remain queued.
   A repeated request is safe and returns the existing deletion state.

Do not call `delete_workout` for a completed or activity-matched workout. If the
server rejects it for that reason, explain that the historical activity link is
protected. If the `coach` authorization is missing, ask the user to reconnect
Swim Coach. Never claim that recorded Garmin activities were removed.

Reply in Brazilian Portuguese unless the user uses another language.
