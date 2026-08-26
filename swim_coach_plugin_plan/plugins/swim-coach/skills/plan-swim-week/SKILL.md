---
name: plan-swim-week
description: Generate, save, and explain a weekly pool-swimming plan from the athlete's goal, availability, recent swims, feedback, and versioned rules. Use for English or Portuguese requests to plan next week, adjust weekly volume or focus, or fit sessions into available time.
---

# Plan a swim week

1. Call `get_coach_context` to resolve the active goal, pool,
   availability, constraints, and athlete timezone.
2. Call `get_workouts` with `week_start` to identify existing sessions. Use
   absolute dates and require the Monday that begins the week.
3. Call `get_swims` when recent adherence, endurance, pace, consistency, or
   confidence affects the plan. Qualify the result if Garmin data is stale.
4. Call `generate_week` once with the requested constraints:
   `session_count`, `max_session_duration_minutes`, `focus`,
   and `avoid_high_intensity`. The returned sessions are already saved and
   scheduled locally; do not add a review or approval protocol.
5. Present target volume, dated sessions, purposes, duration caps, and warnings.
6. Publish sessions to Garmin only when the user explicitly asks. In that case,
   call `publish_workout` once for each returned workout ID and report the
   outcome compactly.

Respect the backend's conservative load, recovery, pool-distance, and intensity
limits. Do not roll missed work forward, diagnose pain, prescribe treatment, or
override a pain or fatigue warning. If relevant pain is reported, explain the
reduction and advise stopping and seeking qualified care when appropriate.

Reply in Brazilian Portuguese unless the user uses another language. Base every
claim on returned context, plan output, and sample confidence;
do not invent availability, infer hidden health state, or promise goal dates.
