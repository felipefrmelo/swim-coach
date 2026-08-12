---
name: adapt-workout
description: Propose a safe, reviewable change or reschedule for an existing Swim Coach pool workout. Use for English or Portuguese requests to shorten, simplify, move, or adapt the next swim because of time, fatigue, equipment, calendar, or technique needs. This workflow creates a proposal only and never silently applies or publishes it.
---

# Adapt a swim workout

1. Call `get_training_context` and `get_today_workout` or `get_week_plan` to
   identify the owned workout and current constraints.
2. If the user wants a different date, call `propose_workout_reschedule` with
   the exact workout and requested date/time.
3. For a content change, preserve the canonical pool length, produce a complete
   valid canonical definition, and call `propose_workout_change` with the
   current revision and full definition.
4. Call `get_action_proposal` for the returned ID and verify the persisted
   before/after impact, expiry, hash, and status.
5. Present the returned before/after impact, expiry, and proposal status. State
   clearly that the workout has not been changed, approved, or published.
6. Direct the user to review the proposal. P08 does not execute local adaptation
   proposals through this Skill.

Never call approval, execution, or Garmin-publication tools in this workflow.
Never edit a published revision in
place. Do not increase intensity when pain, illness, or severe fatigue is
reported; suggest stopping and seeking qualified care when appropriate without
diagnosing a condition.

Reply in Brazilian Portuguese unless the user uses another language. Base the
proposal only on returned data and the user's stated constraint. If the workout,
pool, or current revision is missing, explain the missing prerequisite.
