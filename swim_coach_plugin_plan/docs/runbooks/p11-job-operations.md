# P11 job operations runbook

## Observe

Open `/operations` as the authenticated owner. The screen exposes only job type,
state, attempt count, redacted error code, oldest active age and terminal count.
Payloads, tokens, FIT data and provider identifiers are never returned.

Healthy personal baseline:

- oldest active age returns to zero after the worker catches up;
- `NEEDS_RECONCILIATION` is never retried blindly;
- a terminal job only displays retry when its stored error says `retryable=true`
  and `ambiguous_external_effect` is absent;
- notification count is bounded by stable per-event dedupe keys.

## Recover

1. Inspect the redacted error code and current integration health.
2. Reauthenticate Garmin when the code requires it; do not retry authentication
   failures in a loop.
3. Use **Tentar de novo** only when the UI offers it. The REST boundary verifies
   ownership, terminal state, safe classification and idempotency again.
4. For `NEEDS_RECONCILIATION`, read provider state first and follow the Garmin
   reconciliation flow; never convert it to a blind retry.
5. Restarting worker replicas is safe: leases expire and recurring jobs retain
   stable keys.

## Retention and rollback

Finished jobs older than `SWIM_COACH_JOB_RETENTION_DAYS` are purged by the
automation tick. Audit/outbox/notification history is not part of that purge.

Disable `SWIM_COACH_AUTOMATION_ENABLED` to stop creating periodic work while
manual sync, feedback and planning paths remain available. Unregistering the
service worker from the browser disables offline behavior; it does not delete
server data.
