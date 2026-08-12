---
name: review-latest-swim
description: Review and explain the user's latest or selected pool swim with Swim Coach read-only data. Use for requests in English or Portuguese to analyze, review, compare, or understand a recent swimming activity, including “como foi minha última natação?” and planned-versus-completed questions.
---

# Review a pool swim

1. If the user supplies an activity ID, call `get_swim_activity` for that ID.
2. Otherwise call `list_recent_swims` with `limit=1`. If it returns an activity,
   call `get_swim_activity` with its internal activity ID.
3. Call `get_sync_status` to qualify freshness. Do not trigger a sync.
4. Respect the tool's data-quality flags and warnings. Use only returned metrics.
5. When a planned-workout match exists, compare planned and completed values;
   otherwise state that no reliable match is available.
6. Report two to four useful facts, then separate any inference from observation.
   Prefer concise prose over a metric dump.

If no activity exists, explain that clearly and report the returned sync state.
If authorization is missing, ask the user to connect or authorize Swim Coach;
never request a password, token, FIT file, or Garmin identifier in chat.

Reply in Brazilian Portuguese unless the user uses another language. Use absolute
dates when relative dates could be ambiguous. Do not diagnose pain or health
conditions. Never call write, sync-run, proposal, approval, execution, job-retry,
or Garmin-publication tools, even if the user asks within this workflow.
