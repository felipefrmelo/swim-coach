---
name: diagnose-sync
description: Diagnose missing or stale Garmin swimming data, inspect connection and job status, and safely start or retry synchronization when appropriate.
---

# Diagnose Garmin sync

1. Call `get_sync_status`.
2. Identify connection state, last success, cursor/staleness, active job, and sanitized failure.
3. When no job is running and the action is appropriate, offer or call `sync_garmin_activities` according to the user's request.
4. Follow returned job with `get_job_status`.
5. Use `retry_failed_job` only when the backend marks it retryable and not ambiguous.
6. Recommend reconnecting only for auth failures.
7. Never request credentials in the conversation.
