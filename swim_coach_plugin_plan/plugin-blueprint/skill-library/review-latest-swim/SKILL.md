---
name: review-latest-swim
description: Review and explain the user's latest or selected pool swim using Swim Coach data, including planned-versus-completed comparison when available.
---

# Review a pool swim

Use this workflow when the user asks how a swim went, asks for analysis, or references a recent/specific pool activity.

1. Resolve the activity. When no ID/date is given, call `list_recent_swims` with limit 1.
2. Call `get_swim_activity` for the selected ID.
3. Check data quality, staleness, and whether a planned workout match exists.
4. State the key facts first: distance, time/pace, completion, consistency/fade, and feedback status.
5. Compare planned versus completed only when the tool returns a match.
6. Clearly label inferences. Do not invent technique problems from pace alone.
7. When feedback is missing, offer a short post-swim check-in.
8. Never diagnose pain or provide medical treatment advice.

If data is absent or stale, use `get_sync_status` and offer a safe sync. Keep the final answer concise, numerical, and in the user's language.
