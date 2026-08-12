---
name: diagnose-sync
description: Diagnose and, when explicitly requested, safely queue Garmin activity synchronization using Swim Coach. Use when a user says a swim is missing, delayed, stale, not synchronized, asks whether Garmin is connected, why an import failed, or asks to run/retry a sync in English or Portuguese.
---

# Diagnose Garmin sync

1. Call `get_sync_status` once.
2. Explain connection state, last successful sync, staleness, and active or
   failed jobs without exposing internal details.
3. Distinguish “no recent activity exists” from stale local data and from a
   connection that requires authorization.
4. If the user explicitly asks to synchronize and `sync:run` is authorized,
   call `sync_garmin_activities` once with a stable idempotency key. Then call
   `get_job_status` when a job ID is returned.
5. Retry only when `get_job_status` explicitly says the failure is retryable,
   the user asks to retry, and no ambiguous external effect is reported. Use
   `retry_failed_job` once with a new stable idempotency key.

If authorization is missing, direct the user to connect or reauthorize Swim
Coach. Never request a Garmin password, MFA code, token, FIT file, or private ID
in chat. Do not claim recovery until a later status read confirms success. Never
call workout proposal, approval, execution, feedback, or Garmin-publication
tools in this Skill.

Reply in Brazilian Portuguese unless the user uses another language. Use
absolute timestamps when ambiguity matters.
