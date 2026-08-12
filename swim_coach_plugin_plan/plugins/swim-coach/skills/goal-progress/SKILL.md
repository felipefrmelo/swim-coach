---
name: goal-progress
description: Explain evidence-based progress toward the user's active swimming goal with Swim Coach read-only data. Use for English or Portuguese questions about goal status, pace or endurance gaps, trends, distance remaining, sample quality, or progress toward targets such as 2,000 meters in 45 minutes.
---

# Explain swimming goal progress

1. Call `get_training_context` to resolve the active goal and relevant context.
2. Call `get_goal_progress` for that goal when the first result provides an ID;
   otherwise call it without an ID and let the backend resolve the active goal.
3. Cite the target, current evidence, sample size, data quality, and returned gaps.
4. Distinguish demonstrated pace from the ability to sustain it over the target
   distance. Do not turn a short sample into a completion prediction.
5. Present the most useful next action only when the tool result supplies one.

If there is no active goal or the sample is insufficient, say exactly what is
missing. Never invent a target, recompute domain metrics, or state a guaranteed
date of achievement.

Reply in Brazilian Portuguese unless the user uses another language. Keep the
answer compact and evidence-led. Never call write, sync-run, proposal, approval,
execution, job-retry, or Garmin-publication tools.
