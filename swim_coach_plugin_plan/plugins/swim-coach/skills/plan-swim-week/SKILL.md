---
name: plan-swim-week
description: Create, review, and materialize an approval-gated rolling pool-swimming cycle from the athlete's goal, availability, recent swims, feedback, notes, and versioned rules. Use for English or Portuguese requests to start a cycle, plan the next week, or adapt future training.
---

# Plan and adapt a swim cycle

1. Call `get_coach_context`, then `get_workouts` and `get_swims` only when their
   additional detail is needed. Use absolute dates and Monday week starts.
2. If no active cycle exists, explain the duration and rolling horizon, call
   `propose_training_plan`, and show its strategy, first detailed week, diff,
   and exact hash. Do not apply it in the same response unless the user has
   explicitly approved that exact displayed proposal.
3. After exact approval, call `apply_plan_revision` with the returned plan,
   proposal, expected revision, and hash. Its job materializes the first week
   locally; Garmin is unchanged.
4. Call `get_training_plan` for the current revision, session bindings, locks,
   notes, and materialization status.
5. Persist durable athlete or coach context with `add_plan_note`; choose the
   narrowest plan, week, session, or activity scope and the truthful author.
   Use `set_training_plan_status` for an explicit pause or resume. Use
   `skip_plan_session` only when the athlete intentionally resolves a session
   as missed; never use it merely because an activity has not synchronized yet.
6. To adapt after a week, call `review_training_plan`. Distinguish deterministic
   facts from your interpretation and respect its eligibility and confidence cap.
7. Choose one explicit decision and call `propose_plan_revision`. Show the
   evidence, rationale, impact, diff, and exact hash. A `PROGRESS` proposal must
   not bypass pain, low-confidence, or comparable-evidence guards.
8. Call `apply_plan_revision` only after the athlete approves that exact
   proposal. Never infer approval from a request to review or explain it.
9. Use `generate_week` only for an active plan's detailed week, primarily to
   retry idempotent local materialization. It no longer creates standalone weeks.
10. Publish sessions with `publish_workout` only when the athlete explicitly asks.

Respect the backend's conservative load, recovery, pool-distance, and intensity
limits. Do not roll missed work forward, diagnose pain, prescribe treatment, or
override a pain or fatigue warning. If relevant pain is reported, explain the
reduction and advise stopping and seeking qualified care when appropriate.

The rolling horizon contains one concrete week, one outline, and strategic
future weeks. A final 2,000 m test is conditional on intermediate evidence; do
not promise that an eight-week cycle will achieve the goal.

Reply in Brazilian Portuguese unless the user uses another language. Base every
claim on returned context, plan output, and sample confidence;
do not invent availability, infer hidden health state, or promise goal dates.
