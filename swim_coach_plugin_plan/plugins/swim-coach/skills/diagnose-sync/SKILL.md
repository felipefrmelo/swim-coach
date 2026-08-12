---
name: diagnose-sync
description: Diagnose Garmin connection and activity-sync health using Swim Coach read-only status. Use when a user says a swim is missing, delayed, stale, not synchronized, or asks in English or Portuguese whether Garmin is connected or why an import or sync job failed.
---

# Diagnose Garmin sync

1. Call `get_sync_status` once.
2. Explain the returned connection state, last successful sync, staleness, cursor,
   and active or failed jobs without exposing internal error details.
3. Distinguish “no recent activity exists” from “the data may be stale” and from
   “the connection requires authorization.”
4. Follow only the safe next actions returned by the tool. In release `0.1.0`,
   describe how the user can act outside this workflow; do not trigger a sync.

If authorization is missing, direct the user to connect or reauthorize Swim
Coach. Never request a Garmin password, MFA code, token, FIT file, or private ID
in chat. Do not retry jobs or claim recovery before a later read confirms it.

Reply in Brazilian Portuguese unless the user uses another language. Use
absolute timestamps when ambiguity matters. Never call write, sync-run, proposal,
approval, execution, job-retry, or Garmin-publication tools.
