---
name: post-swim-checkin
description: Record bounded post-swim feedback for a recent Swim Coach activity. Use when a user in English or Portuguese reports RPE, technique quality, pain signal, or notes after swimming, asks to log how a session felt, or wants a post-workout check-in.
---

# Record a post-swim check-in

1. Resolve the activity with `get_swims`, unless the user supplied its internal
   activity ID.
2. Collect only missing required fields: RPE from 1–10, technique from 1–5 (or
   poor/fair/ok/good/excellent), and whether pain was present. Pain location and
   intensity and a short note are optional.
3. When the user's message clearly asks to record the check-in, call
   `save_feedback` once. Otherwise ask only for the missing values.
4. Report that the feedback was saved without exposing provider identifiers or
   internal version/idempotency fields.

Do not diagnose pain, infer an injury, or prescribe treatment. If pain is severe,
new, or alarming, recommend stopping and seeking qualified medical care in plain
language. Never request Garmin credentials, tokens, FIT files, or private IDs.
Do not alter or publish a workout unless the user separately asks for it.

Reply in Brazilian Portuguese unless the user uses another language. If the
activity cannot be found or write authorization is missing, state that clearly
and provide the returned safe next action.
