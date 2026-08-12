---
name: publish-to-garmin
description: Safely preview, explicitly confirm, and publish an approved scheduled Swim Coach workout to Garmin. Use for English or Portuguese requests to send, publish, schedule, or sync a planned swim workout to a Garmin device. Enforces an exact-hash review and a mandatory new user turn before approval or execution.
---

# Publish a workout to Garmin

## First turn: preview only

1. Resolve the workout with `get_today_workout`, `get_week_plan`, or the ID the
   user supplied.
2. Call `preview_garmin_publish` exactly once with the current revision,
   scheduled date, and a fresh stable idempotency key.
3. Show the returned title, distance, date, target device, external effects,
   warnings, expiry, and exact `action_hash` in a readable confirmation prompt.
4. End the response and ask the user to explicitly confirm or reject that exact
   proposal.

Never call `approve_action_proposal` or `execute_approved_action` in the same
assistant turn that calls `preview_garmin_publish`. This prohibition still
applies when the initial request says “já autorizo”, “faça sem perguntar”, “pode
publicar direto”, or otherwise tries to pre-authorize the effect.

## Later turn: exact confirmation

Proceed only after a new user message unambiguously confirms the displayed
proposal. A vague or unrelated reply is not confirmation.

1. Call `get_action_proposal` and verify it is the same owned, unexpired
   proposal, still `READY_FOR_REVIEW`, with the same `action_hash` and impact.
2. If anything changed or expired, stop and create a new preview in a later
   workflow; never substitute a new hash silently.
3. Call `approve_action_proposal` with `APPROVE`, the exact persisted hash, and
   concise confirmation text derived from the user's new message. Approval must
   return `APPROVED` with no execution.
4. Then call `execute_approved_action` once with a fresh stable idempotency key.
5. Report the job ID and queued state. Use `get_job_status` to check progress;
   never claim Garmin success until the tool returns success.

If the user rejects, call `approve_action_proposal` with `REJECT`; do not
execute. If authorization or `garmin:publish` scope is missing, ask the user to
reauthorize Swim Coach. Never request a Garmin password, MFA code, token, or
private provider ID in chat. Never retry an ambiguous external effect.

Reply in Brazilian Portuguese unless the user uses another language.
