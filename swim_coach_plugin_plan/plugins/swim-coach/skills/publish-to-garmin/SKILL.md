---
name: publish-to-garmin
description: Publish or update a scheduled Swim Coach workout on Garmin directly. Use for English or Portuguese requests to send, publish, schedule, republish, or move a planned swim workout on Garmin.
---

# Publish a workout to Garmin

1. Resolve the workout with `get_workouts` using the supplied ID, date, or week.
   Ask a short question only if multiple workouts match or no date is available.
2. If the user's request includes an edit, call `save_workout` first with the
   complete updated definition and schedule.
3. Call `publish_workout` once for the resolved workout. A clear request such as
   “publique”, “mande para o Garmin”, or “ajuste e publique” authorizes that
   call; do not invent a preview/hash/approval sequence.
4. Report whether the workout was queued or already current. A repeated request
   is safe: the server updates the existing Garmin workout and calendar binding
   idempotently.

If the `coach` authorization is missing, ask the user to reconnect Swim Coach.
Never request a Garmin password, MFA code, token, or private provider ID in chat.
Do not claim completion when the tool only reports a queued operation.

Reply in Brazilian Portuguese unless the user uses another language.
