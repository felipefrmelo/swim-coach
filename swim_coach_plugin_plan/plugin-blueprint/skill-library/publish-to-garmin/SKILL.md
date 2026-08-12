---
name: publish-to-garmin
description: Preview, explicitly confirm, approve, and execute publication or scheduling of an exact Swim Coach workout revision to Garmin.
---

# Publish to Garmin safely

This workflow has a hard confirmation boundary.

1. Resolve the exact workout and revision.
2. Call `preview_garmin_publish`; this must not contact Garmin.
3. Present title, distance, pool, schedule date, target device, warnings, and proposal expiry.
4. Ask the user to explicitly confirm the exact action.
5. Stop the turn. Never infer approval from the original request.
6. Only after a later explicit confirmation, call `approve_action_proposal` with the exact `action_hash`.
7. Then call `execute_approved_action` with a stable idempotency key.
8. If a job is returned, call `get_job_status` only as needed.
9. For ambiguous provider outcomes, report reconciliation required and never blindly retry.

Never ask for a Garmin password in chat.
