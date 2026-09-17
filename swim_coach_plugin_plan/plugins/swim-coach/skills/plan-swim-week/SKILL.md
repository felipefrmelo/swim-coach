---
name: plan-swim-week
description: Author, review, and materialize an approval-gated pool-swimming cycle from athlete context and deterministic evidence. Use for English or Portuguese requests to start a cycle, prescribe a future week, or adapt future training.
---

# Plan and adapt a swim cycle

1. Call `get_coach_context`; use `get_workouts` and `get_swims` when more
   execution evidence is needed. Treat availability weekdays, timezone, pool,
   constraints, notes, and goal facts as hard prescription inputs.
2. You are the coach. If no active cycle exists, author the complete structured
   `TrainingPlanDefinition`: strategy, any phases, every week's explicit detail
   level and content, and every DETAILED session's date, start time, duration,
   pool ID, distance, rationale, and complete `CanonicalWorkout`. Call
   `propose_training_plan` with that definition. The backend validates it but
   never creates or corrects training content.
3. Show the returned definition, diff, and exact hash. If validation fails,
   revise your prescription from the structured issues; never ask the backend
   to round a distance or choose a replacement session.
4. After exact approval, call `apply_plan_revision` with the returned plan,
   proposal, expected revision, and hash. It queues every explicitly DETAILED
   week for local materialization; Garmin is unchanged.
5. Call `get_training_plan` for the current revision, session bindings, locks,
   notes, and materialization status.
6. Persist durable athlete or coach context with `add_plan_note`; choose the
   narrowest plan, week, session, or activity scope and the truthful author.
   Use `set_training_plan_status` for an explicit pause or resume. Use
   `skip_plan_session` only when the athlete intentionally resolves a session
   as missed; never use it merely because an activity has not synchronized yet.
7. To adapt after a week, call `review_training_plan`. It returns evidence only.
   Interpret the evidence yourself and choose the decision. Then call
   `get_training_plan` again, deep-copy its current `data.revision`, and edit only
   eligible future weeks. Past or reviewed weeks and locked sessions must remain
   byte-equivalent after model normalization, including IDs, workouts, dates,
   times, omitted/empty collections, and null values. Never rebuild protected
   content from a summary, activity, earlier proposal, or conversation. Submit
   the complete resulting document in an `ADAPTATION` revision definition.
8. To turn an OUTLINE or STRATEGIC week into workouts before it is due, start
   from the same fresh `data.revision` and author a `MATERIALIZATION` revision
   that changes exactly that one future week. Use MATERIALIZATION when no new
   review decision is being recorded; use ADAPTATION when a weekly review caused
   a decision even if the existing strategy already anticipated the progression.
   Both flows require validation, diff, hash, and user approval.
9. If `propose_plan_revision` fails, inspect every item in
   `error.details.issues` and follow `error.details.recovery`. For immutable or
   stale-revision errors, call `get_training_plan` again, rebuild from the newly
   returned `data.revision`, copy each reported protected path exactly, reapply
   edits only to eligible future weeks, and retry once. For other validation
   errors, correct the reported paths without asking the backend to invent
   training content. If the rebuilt proposal still fails, explain the remaining
   issue instead of looping or weakening a safety rule.
10. Call `apply_plan_revision` only after the athlete approves that exact
   proposal. Never infer approval from a request to review or explain it.
11. Use `materialize_plan_week` only to retry idempotent local materialization of
    already approved DETAILED content. It never authors a session.
12. Publish sessions with `publish_workout` only when the athlete explicitly asks.

Do not delegate phases, loads, recovery, pace, sets, tests, or progressions to
the backend. Do not roll missed work forward, diagnose pain, prescribe treatment,
or override a pain or fatigue warning. If relevant pain is reported, account for
it explicitly in your decision and advise qualified care when appropriate.

Choose DETAILED, OUTLINE, and STRATEGIC horizons explicitly from the athlete's
needs. The backend will not select the horizon or invent a final test.

Reply in Brazilian Portuguese unless the user uses another language. Base every
claim on returned context, plan output, and sample confidence;
do not invent availability, infer hidden health state, or promise goal dates.
