---
name: post-swim-checkin
description: Record bounded post-swim feedback for a recent Swim Coach activity. Use when a user in English or Portuguese reports RPE, technique quality, pain signal, or notes after swimming, asks to log how a session felt, or wants a post-workout check-in.
---

# Record a post-swim check-in

1. Resolve the activity with `get_swims`, unless the user supplied its internal
   activity ID, and inspect `session_evaluation` before asking questions.
2. Treat Garmin perceived effort and Garmin feeling as distinct imported facts.
   Never reinterpret feeling as technique. If an effective Garmin RPE already
   exists, do not ask the athlete to repeat it.
3. Collect only information the athlete wants to add or override. Technique,
   pain and notes are optional. Ask for RPE only when no effective RPE exists or
   when the athlete explicitly wants to override it; ask for feeling only for an
   explicit override. Pain location and intensity are required only when pain is
   reported.
4. When the user's message clearly asks to record manual additions or overrides,
   call `save_feedback` once. Otherwise report the imported Garmin assessment and
   ask at most for the genuinely missing information needed by the request.
5. Report what was imported and what was saved manually without exposing
   provider identifiers or internal version/idempotency fields.

Do not diagnose pain, infer an injury, or prescribe treatment. If pain is severe,
new, or alarming, recommend stopping and seeking qualified medical care in plain
language. Never request Garmin credentials, tokens, FIT files, or private IDs.
Do not alter or publish a workout unless the user separately asks for it.

Reply in Brazilian Portuguese unless the user uses another language. If the
activity cannot be found or write authorization is missing, state that clearly
and provide the returned safe next action.
