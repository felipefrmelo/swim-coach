---
name: plan-swim-week
description: Propose or review a weekly pool-swimming plan using the athlete's goal, availability, recent Garmin activities, feedback, and versioned training rules.
---

# Plan a swim week

1. Call `get_training_context`, `get_week_plan`, `list_recent_swims`, and `get_goal_progress` as needed.
2. Check `get_sync_status` when recent data may be stale.
3. Resolve the target week using the athlete timezone and absolute dates.
4. Call `propose_week_plan` with structured constraints and user notes.
5. Present total distance, session purposes, key changes, recovery spacing, and warnings.
6. Treat the result as a proposal. Never approve, execute, or publish it automatically.
7. Invite a specific revision rather than asking a vague question.

Do not increase load beyond the backend rules. Do not treat pain feedback as a diagnosis.
