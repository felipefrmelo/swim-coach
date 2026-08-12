---
name: post-swim-checkin
description: Record bounded post-swim feedback for a recent Swim Coach activity. Use when a user in English or Portuguese reports RPE, technique quality, pain signal, or notes after swimming, asks to log how a session felt, or wants a post-workout check-in.
---

# Record a post-swim check-in

1. Resolve the owned activity with `list_recent_swims` and
   `get_swim_activity`, unless the user supplied its internal activity ID.
2. Collect only missing required fields: RPE from 1–10, technique from 1–5 (or
   poor/fair/ok/good/excellent), and whether pain was present. Pain location and
   intensity and a short note are optional.
3. Summarize the values and, when the user's message already clearly asks to
   record them, call `record_session_feedback` once with a stable idempotency
   key. Otherwise ask before writing.
4. Report the stored feedback ID/version without exposing provider identifiers.

Do not diagnose pain, infer an injury, or prescribe treatment. If pain is severe,
new, or alarming, recommend stopping and seeking qualified medical care in plain
language. Never request Garmin credentials, tokens, FIT files, or private IDs.
Never publish, approve, execute, reschedule, or adapt a workout in this Skill.

Reply in Brazilian Portuguese unless the user uses another language. If the
activity cannot be found or write authorization is missing, state that clearly
and provide the returned safe next action.
