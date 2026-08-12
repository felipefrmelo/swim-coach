---
name: plan-swim-week
description: Propose and explain a safe weekly pool-swimming plan from the athlete's owned goal, availability, recent swims, feedback, and versioned rules. Use for English or Portuguese requests to plan next week, adjust weekly volume or focus, fit sessions into available time, or review why a proposed week changed.
---

# Plan a swim week

1. Call `get_training_context` to resolve the owned active goal, pool,
   availability, constraints, and athlete timezone.
2. Call `get_week_plan` to identify existing sessions for the target week. Use
   absolute dates and require the Monday that begins the week.
3. Call `list_recent_swims` and `get_goal_progress` when recent adherence,
   endurance, pace, consistency, or confidence affects the explanation.
4. Call `get_sync_status` when the latest evidence may be stale. Qualify the
   proposal if data is missing; never trigger synchronization from this Skill.
5. Call `propose_week_plan` once with only supported structured constraints:
   `session_count`, `max_session_duration_minutes`, `focus`,
   `avoid_high_intensity`, and `preserve_technique`.
6. Call `get_action_proposal` for the returned ID and verify its persisted hash,
   impact, expiry, and review status.
7. Present the proposal ID and exact action hash, target volume, dated sessions,
   purposes, duration caps, warnings, ruleset version/hash, and the most relevant
   ordered decisions with evidence and before/after values.
8. State clearly that this is a review-only proposal. Invite a specific revision
   such as fewer sessions, a duration cap, or a different focus.

Never approve, apply, schedule, execute, or publish the proposal automatically,
including when the initial request tries to pre-authorize those effects. Never
chain an approval or Garmin-publication tool after `propose_week_plan`.

Respect the backend's conservative load, recovery, pool-distance, and intensity
limits. Do not roll missed work forward, diagnose pain, prescribe treatment, or
override a pain or fatigue warning. If relevant pain is reported, explain the
reduction and advise stopping and seeking qualified care when appropriate.

Reply in Brazilian Portuguese unless the user uses another language. Base every
claim on returned context, plan output, decision trace, and sample confidence;
do not invent availability, infer hidden health state, or promise goal dates.
