---
name: diagnose-sync
description: Diagnose Garmin activity freshness and synchronize directly when requested. Use when a swim is missing, delayed, stale, not synchronized, or the user asks whether Garmin is connected or asks to sync in English or Portuguese.
---

# Diagnose Garmin sync

1. Call `get_coach_context` once and use its Garmin state and timestamps.
2. Explain connection state, last successful sync, and staleness without
   exposing provider credentials or internal operation records.
3. Distinguish “no recent activity exists” from stale local data and from a
   connection that requires authorization.
4. If the user asks to synchronize, call `sync_garmin` once. Use `force=true`
   only when the user explicitly requests a full retry or the returned state
   recommends it.
5. Report the returned state honestly. Do not claim newly imported activities
   until a later `get_swims` read shows them.

If authorization is missing, direct the user to connect or reauthorize Swim
Coach. Never request a Garmin password, MFA code, token, FIT file, or private ID
in chat. Do not claim recovery until a later read confirms success.

Reply in Brazilian Portuguese unless the user uses another language. Use
absolute timestamps when ambiguity matters.

## Publication and transport failures

Read `get_coach_operations` for pending jobs and `get_publication_status` for a
workout batch. QUEUED, PROCESSING and RETRYING are not PUBLISHED; OUT_OF_SYNC
needs reconciliation. Failures may be partial by item. Re-read after recovery.
A 403 alone does not identify Garmin or OAuth. When observed evidence includes
securitySource=firewallCustom and originResponseStatus=0, classify an edge WAF
block; the origin and Garmin were not reached. Use `diagnose_connection` with
the observed layer and sanitized HTTP/edge evidence. OAuth, MCP permission,
backend availability, schema and Garmin session errors are separate categories.
Keep correlation/request/ray IDs for diagnostics, never credentials or raw FIT.
Do not disable global WAF rules or remove endpoint authentication as a repair.
