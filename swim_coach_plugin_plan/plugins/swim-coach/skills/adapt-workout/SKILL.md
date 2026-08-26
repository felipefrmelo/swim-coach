---
name: adapt-workout
description: Edit or reschedule an existing Swim Coach pool workout directly. Use for English or Portuguese requests to shorten, simplify, move, or adapt a swim because of time, fatigue, equipment, calendar, or technique needs.
---

# Adapt a swim workout

1. Use `get_coach_context` and `get_workouts` to identify the workout and current
   constraints. Ask a short question only if more than one workout matches or a
   required date is missing.
2. Build the complete canonical definition, preserving the configured pool
   length and unaffected blocks.
3. Call `save_workout` once with the workout ID, definition, requested date and
   time, and a concise change reason. The server preserves revision history.
4. Report the new distance, revision, and schedule. Do not mention internal
   hashes, approval states, concurrency fields, or idempotency keys.
5. Call `publish_workout` only when the user also asks to send the result to
   Garmin. A clear request such as “ajuste e publique” is sufficient.

Do not increase intensity when pain, illness, or severe fatigue is reported.
Suggest stopping and seeking qualified care when appropriate without diagnosing
a condition.

Reply in Brazilian Portuguese unless the user uses another language. Base the
change only on returned data and the user's stated constraint. If the workout,
pool, or current revision is missing, explain the missing prerequisite.
