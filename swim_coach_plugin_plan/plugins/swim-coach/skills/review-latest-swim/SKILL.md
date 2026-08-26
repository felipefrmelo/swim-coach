---
name: review-latest-swim
description: Review and explain the user's latest or selected pool swim with Swim Coach read-only data. Use for requests in English or Portuguese to analyze, review, compare, or understand a recent swimming activity, including “como foi minha última natação?” and planned-versus-completed questions.
---

# Review a pool swim

1. Call `get_swims` with the supplied activity ID, or with `limit=1` for the
   latest swim.
2. Call `get_coach_context` only when Garmin freshness or the active goal is
   relevant to the question.
3. Respect the tool's data-quality flags and warnings. Use only returned metrics.
4. When a planned-workout match exists, compare planned and completed values;
   otherwise state that no reliable match is available.
5. Report two to four useful facts, then separate any inference from observation.
   Prefer concise prose over a metric dump.

If no activity exists, explain that clearly and report the returned sync state.
If authorization is missing, ask the user to connect or authorize Swim Coach;
never request a password, token, FIT file, or Garmin identifier in chat.

Reply in Brazilian Portuguese unless the user uses another language. Use absolute
dates when relative dates could be ambiguous. Do not diagnose pain or health
conditions. Do not modify data unless the user also makes a concrete write
request.
